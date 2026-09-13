"""Glue: media file -> moderation gate -> transcript + snapshots -> summary -> saved files."""
from __future__ import annotations

import datetime as _dt
import shutil
from pathlib import Path
from typing import Callable, Optional

import config
import moderation
import snapshots
import summarizer
import transcriber

# progress(stage: str, fraction: float, message: str)
StageProgressFn = Optional[Callable[[str, float, str], None]]


def run(media_path, progress: StageProgressFn = None, out_stem: Optional[str] = None) -> dict:
    media_path = Path(media_path)

    def stage(name: str):
        def cb(frac: float, msg: str) -> None:
            if progress:
                progress(name, frac, msg)
        return cb

    stem = (out_stem or media_path.stem).strip() or "transcript"
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    prefix = config.OUTPUT_DIR / f"{stem}-{stamp}"
    transcript_file = prefix.with_name(prefix.name + "-transcript.txt")
    summary_file = prefix.with_name(prefix.name + "-summary.md")
    frames_dir = prefix.with_name(prefix.name + "-frames")

    # 1. snapshots come first - they also serve as the moderation sample, so
    #    the content check happens BEFORE any transcription work starts.
    sample_count = config.SNAPSHOT_COUNT
    if config.MODERATION_ENABLED:
        sample_count = max(sample_count, config.MODERATION_SAMPLE_COUNT)

    shots = []
    try:
        shots = snapshots.extract(media_path, frames_dir, count=sample_count, progress=stage("snapshots"))
    except Exception as exc:  # never let frame extraction break the run
        if progress:
            progress("snapshots", 1.0, f"Snapshots skipped: {exc}")

    # 2. moderation gate - reject explicit/18+ content before transcribing it.
    if config.MODERATION_ENABLED and shots:
        if progress:
            progress("moderation", 0.0, "Checking content")
        verdict = moderation.check_frames([s["file"] for s in shots])
        if progress:
            progress("moderation", 1.0, "Content check complete")
        if verdict:
            shutil.rmtree(frames_dir, ignore_errors=True)
            raise moderation.ContentBlockedError(
                "This file was blocked: it appears to contain explicit/18+ content, "
                "which this app does not transcribe, summarize, or store.",
                verdict,
            )

    # Trim the display snapshot set back down to the user's configured count
    # if it was over-sampled above to satisfy the moderation minimum.
    if config.SNAPSHOT_COUNT <= 0:
        for s in shots:
            Path(s["file"]).unlink(missing_ok=True)
        shots = []
    elif len(shots) > config.SNAPSHOT_COUNT:
        for s in shots[config.SNAPSHOT_COUNT:]:
            Path(s["file"]).unlink(missing_ok=True)
        shots = shots[:config.SNAPSHOT_COUNT]

    # 3. transcribe - only reached once the content has cleared moderation.
    tr = transcriber.transcribe(media_path, progress=stage("transcribe"))

    # 4. summarize
    summary = summarizer.summarize(
        tr["timestamped"],
        meta={
            "source": media_path.name,
            "duration": tr["duration"],
            "language": tr["language"],
        },
        progress=stage("summarize"),
    )

    transcript_file.write_text(tr["timestamped"] or "(no speech detected)", encoding="utf-8")
    summary_file.write_text(summary, encoding="utf-8")

    if progress:
        progress("done", 1.0, "Complete")

    return {
        "transcript": tr["timestamped"],
        "plain_text": tr["text"],
        "summary": summary,
        "language": tr["language"],
        "duration": tr["duration"],
        "source": media_path.name,
        "snapshots": shots,
        "frames_dir": str(frames_dir),
        "transcript_file": str(transcript_file),
        "summary_file": str(summary_file),
    }
