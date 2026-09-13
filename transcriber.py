"""Local speech-to-text with faster-whisper.

faster-whisper decodes audio straight from the video container via its bundled
PyAV/FFmpeg libraries, so no separate FFmpeg install is required for common
formats (mp4, mkv, mov, webm, mp3, wav, m4a, ...).
"""
from __future__ import annotations

import datetime as _dt
from typing import Callable, Optional

import config

ProgressFn = Optional[Callable[[float, str], None]]

_model_cache: dict = {}
_pipeline_cache: dict = {}


def _fmt_ts(seconds: float) -> str:
    total = max(int(seconds), 0)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _get_model():
    key = (config.WHISPER_MODEL, config.WHISPER_DEVICE, config.WHISPER_COMPUTE_TYPE)
    if key not in _model_cache:
        from faster_whisper import WhisperModel  # imported lazily; heavy

        _model_cache[key] = WhisperModel(
            config.WHISPER_MODEL,
            device=config.WHISPER_DEVICE,
            compute_type=config.WHISPER_COMPUTE_TYPE,
        )
    return _model_cache[key]


def _get_pipeline(model):
    """Batched inference pipeline (opt-in via WHISPER_BATCHED) - faster, coarser timestamps."""
    key = id(model)
    if key not in _pipeline_cache:
        from faster_whisper import BatchedInferencePipeline
        _pipeline_cache[key] = BatchedInferencePipeline(model=model)
    return _pipeline_cache[key]


def _has_audio(media_path) -> bool:
    try:
        import av
        with av.open(str(media_path)) as container:
            return any(s.type == "audio" for s in container.streams)
    except Exception:
        return True  # if we cannot tell, let Whisper try


def transcribe(media_path, progress: ProgressFn = None) -> dict:
    """Transcribe a media file.

    Returns a dict with:
      language      detected (or forced) language code
      duration      media duration in seconds
      timestamped   full transcript, one line per segment, "[HH:MM:SS] text"
      text          plain transcript with no timestamps
    """
    if not _has_audio(media_path):
        if progress:
            progress(1.0, "No audio track found - skipping transcription")
        return {"language": None, "duration": 0.0, "timestamped": "", "text": ""}

    model = _get_model()
    if config.WHISPER_BATCHED:
        pipe = _get_pipeline(model)
        segments, info = pipe.transcribe(
            str(media_path),
            language=config.WHISPER_LANGUAGE,
            beam_size=config.WHISPER_BEAM_SIZE,
            batch_size=config.WHISPER_BATCH_SIZE,
        )
    else:
        segments, info = model.transcribe(
            str(media_path),
            language=config.WHISPER_LANGUAGE,
            beam_size=config.WHISPER_BEAM_SIZE,
            vad_filter=True,
        )

    total = float(getattr(info, "duration", 0.0) or 0.0)
    lines: list[str] = []
    plain: list[str] = []

    for seg in segments:  # generator - work streams in as decoding proceeds
        text = (seg.text or "").strip()
        if not text:
            continue
        lines.append(f"[{_fmt_ts(seg.start)}] {text}")
        plain.append(text)
        if progress and total:
            pct = min(seg.end / total, 0.999)
            progress(pct, f"Transcribing {_fmt_ts(seg.end)} / {_fmt_ts(total)}")

    if progress:
        progress(1.0, "Transcription complete")

    return {
        "language": getattr(info, "language", None),
        "duration": total,
        "timestamped": "\n".join(lines),
        "text": " ".join(plain),
    }
