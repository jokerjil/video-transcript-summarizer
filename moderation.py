"""Offline content moderation: blocks explicit/18+ video before it is ever
transcribed, summarized, or saved.

Uses NudeNet (github.com/notAI-tech/NudeNet), an open-source nudity
classifier whose ONNX model ships INSIDE the pip package itself - no
download, no network call, no external service, ever. A handful of frames
sampled from the video are classified; if any frame is flagged with high
confidence, the whole job is rejected before transcription starts.

Limitation, stated plainly: this only looks at sampled video frames. It
cannot screen audio-only files (there is nothing visual to sample), and a
frame-sampling classifier is not a perfect guarantee for either false
positives or false negatives. It is a real, meaningful safety gate, not an
absolute one.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import config

# Detection classes from NudeNet that indicate genuine explicit/18+ content.
# Deliberately excludes classes like MALE_BREAST_EXPOSED, FEET_EXPOSED,
# BELLY_EXPOSED, FACE_*, and all *_COVERED classes, which are common in
# everyday footage (swimming, sports, workouts) and are not explicit content.
_EXPLICIT_CLASSES = frozenset({
    "FEMALE_GENITALIA_EXPOSED",
    "MALE_GENITALIA_EXPOSED",
    "ANUS_EXPOSED",
    "FEMALE_BREAST_EXPOSED",
    "BUTTOCKS_EXPOSED",
})

_detector = None


class ContentBlockedError(Exception):
    """Raised when uploaded media is flagged as explicit/18+ content."""

    def __init__(self, message: str, detail: dict):
        super().__init__(message)
        self.detail = detail


def _get_detector():
    global _detector
    if _detector is None:
        from nudenet import NudeDetector  # imported lazily; loads its bundled ONNX model
        _detector = NudeDetector()
    return _detector


def check_frames(frame_paths: list) -> Optional[dict]:
    """Classify sampled frames for explicit content.

    Returns None if the content looks clear, or a detail dict describing
    what was flagged (frame name, class, confidence) if not. Never raises -
    a classifier error is treated as "cannot tell", not as a block, so a
    corrupt frame never silently locks a legitimate upload out.
    """
    if not config.MODERATION_ENABLED or not frame_paths:
        return None

    detector = _get_detector()
    threshold = config.MODERATION_THRESHOLD
    hits = []
    checked = 0

    for path in frame_paths:
        if not Path(path).is_file():
            continue
        checked += 1
        try:
            detections = detector.detect(str(path))
        except Exception:
            continue  # skip an unreadable frame rather than fail the whole check
        for d in detections:
            if d.get("class") in _EXPLICIT_CLASSES and float(d.get("score", 0)) >= threshold:
                hits.append({
                    "frame": Path(path).name,
                    "class": d["class"],
                    "score": round(float(d["score"]), 3),
                })

    if not hits:
        return None
    return {"frames_checked": checked, "hit_count": len(hits), "hits": hits[:5]}
