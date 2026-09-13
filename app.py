"""Local web UI: drop a video (or paste its path) -> transcript + offline summary.

Run:  python app.py   then open http://127.0.0.1:5000
Everything runs on your machine. No internet, no API key.

Set PUBLIC_MODE=true (see config.py) when deploying this publicly - it turns
on a smaller upload cap, a video-length cap, a concurrency limit, a per-IP
rate limit, and disables the "local file path" field, which is only safe for
a single trusted local user.
"""
from __future__ import annotations

import io
import os
import threading
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file

import config
import pipeline
import report
from snapshots import FRAME_NAME_RE
from util import probe_duration_seconds

app = Flask(__name__)
# Allow the configured cap plus a little multipart overhead.
app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_BYTES + (32 * 1024 * 1024)

JOBS: dict[str, dict] = {}

# ---- Public-deployment safety rails (all no-ops when their config is 0) ----
_job_slots = threading.Semaphore(config.MAX_CONCURRENT_JOBS) if config.MAX_CONCURRENT_JOBS > 0 else None
_rate_lock = threading.Lock()
_rate_log: dict[str, deque] = defaultdict(deque)


def _rate_limited(ip: str) -> bool:
    if config.RATE_LIMIT_PER_HOUR <= 0:
        return False
    now = time.time()
    with _rate_lock:
        log = _rate_log[ip]
        while log and now - log[0] > 3600:
            log.popleft()
        if len(log) >= config.RATE_LIMIT_PER_HOUR:
            return True
        log.append(now)
        return False


def _new_job() -> str:
    jid = uuid.uuid4().hex[:12]
    JOBS[jid] = {
        "state": "queued",      # queued | running | done | error
        "stage": None,          # snapshots | moderation | transcribe | summarize | done
        "progress": 0.0,
        "message": "Queued",
        "error": None,
        "result": None,
        "created": time.time(),
    }
    return jid


def _run_job(jid: str, media_path: str, cleanup: bool) -> None:
    job = JOBS[jid]
    job["state"] = "running"

    def progress(stage: str, frac: float, msg: str) -> None:
        job["stage"] = stage
        job["progress"] = round(float(frac), 4)
        job["message"] = msg

    held_slot = False
    try:
        if _job_slots is not None:
            if not _job_slots.acquire(blocking=False):
                job["state"] = "error"
                job["error"] = "Server is busy processing another video right now. Please try again shortly."
                job["message"] = "Failed: server busy"
                return
            held_slot = True

        job["result"] = pipeline.run(media_path, progress=progress)
        job["state"] = "done"
        job["stage"] = "done"
        job["progress"] = 1.0
        job["message"] = "Complete"
    except Exception as exc:  # surface any failure to the browser
        job["state"] = "error"
        job["error"] = str(exc)
        job["message"] = f"Failed: {exc}"
    finally:
        if held_slot:
            _job_slots.release()
        if cleanup:
            try:
                Path(media_path).unlink(missing_ok=True)
            except OSError:
                pass


@app.get("/")
def index():
    return render_template("index.html",
                           max_gb=round(config.MAX_UPLOAD_BYTES / 1024 ** 3, 1),
                           whisper=config.WHISPER_MODEL,
                           local_path_enabled=config.LOCAL_PATH_ENABLED,
                           max_minutes=(config.MAX_VIDEO_SECONDS // 60) if config.MAX_VIDEO_SECONDS else 0)


@app.post("/process")
def process():
    if _rate_limited(request.remote_addr or "unknown"):
        return jsonify({"error": "Too many uploads from this address recently. Please try again later."}), 429

    local_path = (request.form.get("local_path") or "").strip().strip('"').strip("'")

    if local_path:
        if not config.LOCAL_PATH_ENABLED:
            return jsonify({"error": "Local file paths are not available on this hosted deployment. "
                                    "Please upload the file instead."}), 403
        src = Path(local_path)
        if not src.is_file():
            return jsonify({"error": f"File not found on this machine: {local_path}"}), 400
        err = _reject_if_too_long(src)
        if err:
            return err
        jid = _new_job()
        threading.Thread(target=_run_job, args=(jid, str(src), False), daemon=True).start()
        return jsonify({"job_id": jid})

    upload = request.files.get("file")
    if upload and upload.filename:
        safe = Path(upload.filename).name
        dest = config.UPLOAD_DIR / f"{uuid.uuid4().hex[:12]}-{safe}"
        upload.save(dest)
        err = _reject_if_too_long(dest)
        if err:
            dest.unlink(missing_ok=True)
            return err
        jid = _new_job()
        threading.Thread(target=_run_job, args=(jid, str(dest), True), daemon=True).start()
        return jsonify({"job_id": jid})

    return jsonify({"error": "Provide a file to upload or a local file path."}), 400


def _fmt_duration(seconds: float) -> str:
    seconds = round(seconds)
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    minutes = seconds / 60
    return f"{minutes:.1f} minutes" if minutes < 10 else f"{minutes:.0f} minutes"


def _reject_if_too_long(media_path: Path):
    """None if OK, else a (json, status) tuple to return immediately."""
    if config.MAX_VIDEO_SECONDS <= 0:
        return None
    duration = probe_duration_seconds(media_path)
    if duration > config.MAX_VIDEO_SECONDS:
        return jsonify({"error": f"This file is about {_fmt_duration(duration)} long. "
                                f"This hosted deployment is limited to "
                                f"{_fmt_duration(config.MAX_VIDEO_SECONDS)} per file."}), 413
    return None


@app.get("/status/<jid>")
def status(jid: str):
    job = JOBS.get(jid) or abort(404)
    return jsonify({k: job[k] for k in ("state", "stage", "progress", "message", "error")})


@app.get("/result/<jid>")
def result(jid: str):
    job = JOBS.get(jid) or abort(404)
    if job["state"] != "done":
        return jsonify({"error": "not ready", "state": job["state"]}), 409
    return jsonify(job["result"])


@app.get("/snapshot/<jid>/<name>")
def snapshot(jid: str, name: str):
    job = JOBS.get(jid) or abort(404)
    if job["state"] != "done" or not FRAME_NAME_RE.match(name):
        abort(404)
    path = Path(job["result"]["frames_dir"]) / name
    if not path.is_file():
        abort(404)
    return send_file(path, mimetype="image/jpeg")


def _base_name(job: dict) -> str:
    src = job["result"].get("source") or "video"
    return Path(src).stem or "video"


@app.get("/download/<jid>/<kind>")
def download(jid: str, kind: str):
    job = JOBS.get(jid) or abort(404)
    if job["state"] != "done":
        abort(404)
    res = job["result"]
    stem = _base_name(job)

    if kind in ("transcript", "summary"):
        key = {"transcript": "transcript_file", "summary": "summary_file"}[kind]
        return send_file(res[key], as_attachment=True)

    if kind == "document":  # one self-contained file with everything
        html_doc = report.build_html(res, title=f"{stem} - summary")
        return send_file(io.BytesIO(html_doc.encode("utf-8")),
                         mimetype="text/html", as_attachment=True,
                         download_name=f"{stem}-document.html")

    if kind == "pdf":
        pdf_bytes = report.build_pdf(res, title=f"{stem} - summary")
        return send_file(io.BytesIO(pdf_bytes),
                         mimetype="application/pdf", as_attachment=True,
                         download_name=f"{stem}-document.pdf")

    if kind == "docx":
        docx_bytes = report.build_docx(res, title=f"{stem} - summary")
        return send_file(
            io.BytesIO(docx_bytes),
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            as_attachment=True, download_name=f"{stem}-document.docx")

    if kind == "zip":  # every raw artefact
        blob = report.build_zip(res, title=stem)
        return send_file(io.BytesIO(blob), mimetype="application/zip",
                         as_attachment=True, download_name=f"{stem}-bundle.zip")

    abort(404)


@app.get("/health")
def health():
    """Cheap liveness probe for the hosting platform - does no model work."""
    return jsonify({"status": "ok"})


@app.errorhandler(413)
def too_large(_e):
    return jsonify({"error": f"File exceeds the {app.config['MAX_CONTENT_LENGTH']} byte limit."}), 413


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    host = "0.0.0.0" if config.PUBLIC_MODE else "127.0.0.1"
    print(f"Video Transcript Summarizer  ->  http://{host}:{port}  (public mode: {config.PUBLIC_MODE})")
    app.run(host=host, port=port, threaded=True)
