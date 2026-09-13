"""Extract still frames (snapshots) from a video, fully offline via PyAV.

PyAV ships with faster-whisper, so no separate FFmpeg binary is needed.
Audio-only inputs simply yield an empty list.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Optional

import config
from util import hms

ProgressFn = Optional[Callable[[float, str], None]]

FRAME_NAME_RE = re.compile(r"^\d{4}_\d{7}\.jpg$")


def _video_duration_seconds(container, stream) -> float:
    try:
        if stream.duration and stream.time_base:
            return float(stream.duration * stream.time_base)
    except Exception:
        pass
    try:
        import av
        if container.duration:
            return float(container.duration) / av.time_base
    except Exception:
        pass
    return 0.0


def extract(media_path, out_dir, count: Optional[int] = None,
            progress: ProgressFn = None) -> list:
    """Return [{time, hms, name, file}, ...] for evenly spaced frames."""
    import av  # bundled with faster-whisper

    count = int(count or config.SNAPSHOT_COUNT)
    if count <= 0:
        return []
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        container = av.open(str(media_path))
    except Exception:
        return []

    try:
        vstreams = [s for s in container.streams if s.type == "video"]
        if not vstreams:
            return []  # audio-only
        stream = vstreams[0]
        stream.thread_type = "AUTO"

        duration = _video_duration_seconds(container, stream)
        if duration <= 0:
            return []

        # Evenly spaced, biased away from the very first/last frame.
        targets = [duration * (i + 0.5) / count for i in range(count)]
        results: list = []

        for idx, ts in enumerate(targets):
            try:
                offset = int(ts / stream.time_base)
                container.seek(offset, backward=True, stream=stream)
                frame = next(container.decode(stream), None)
                if frame is None:
                    continue
                img = frame.to_image()  # PIL image (RGB)
                w, h = img.size
                maxw = config.SNAPSHOT_WIDTH
                if w > maxw:
                    img = img.resize((maxw, max(1, round(h * maxw / w))))
                name = f"{idx:04d}_{int(round(ts)):07d}.jpg"
                path = out_dir / name
                img.convert("RGB").save(path, "JPEG", quality=82)
                results.append({
                    "time": ts,
                    "hms": hms(ts),
                    "name": name,
                    "file": str(path),
                })
            except Exception:
                continue
            finally:
                if progress:
                    progress((idx + 1) / len(targets), f"Snapshot {idx + 1}/{len(targets)}")

        return results
    finally:
        container.close()
