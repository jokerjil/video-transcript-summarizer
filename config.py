"""Central configuration. Values come from the environment / .env file."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR") or (BASE_DIR / "outputs"))
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR") or (BASE_DIR / "uploads"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ---- Transcription ----
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "auto")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "auto")
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE") or None
# 1 = greedy decoding (fastest, benchmarked no quality loss on this app's use case).
# Raise toward 5 only if you see transcription errors on hard/noisy audio.
WHISPER_BEAM_SIZE = int(os.getenv("WHISPER_BEAM_SIZE", "1"))
# Opt-in "turbo" mode: batches VAD-detected speech chunks for ~25-30% extra
# speed on top of beam_size=1, at the cost of coarser (~30s-block instead of
# per-sentence) timestamps in the transcript, chapters, and snapshot sync.
WHISPER_BATCHED = os.getenv("WHISPER_BATCHED", "false").strip().lower() in ("1", "true", "yes", "on")
WHISPER_BATCH_SIZE = int(os.getenv("WHISPER_BATCH_SIZE", "8"))

# ---- Summarization (fully offline, extractive) ----
SUMMARY_SENTENCES = int(os.getenv("SUMMARY_SENTENCES", "7"))      # sentences in the Overview
SUMMARY_KEY_POINTS = int(os.getenv("SUMMARY_KEY_POINTS", "12"))   # bullets in Key Points
SUMMARY_CHAPTERS = int(os.getenv("SUMMARY_CHAPTERS", "8"))        # timed sections

# ---- Snapshots (video frames) ----
SNAPSHOT_COUNT = int(os.getenv("SNAPSHOT_COUNT", "12"))           # frames to grab (0 disables)
SNAPSHOT_WIDTH = int(os.getenv("SNAPSHOT_WIDTH", "640"))          # max pixel width per frame

# ---- Content moderation (offline, no network call - see moderation.py) ----
# Blocks explicit/18+ video before transcription. Video only - cannot screen
# audio-only files. Not a perfect guarantee; a real, meaningful gate.
MODERATION_ENABLED = os.getenv("MODERATION_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")
MODERATION_THRESHOLD = float(os.getenv("MODERATION_THRESHOLD", "0.5"))   # 0-1, higher = stricter
MODERATION_SAMPLE_COUNT = int(os.getenv("MODERATION_SAMPLE_COUNT", "10"))  # frames sampled for the check

# ---- Web UI ----
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(8 * 1024 ** 3)))

# ---- Public deployment safety rails ----
# All default to "off" so local runs are unaffected. The hosted deployment's
# env config turns these on - see deploy/render.yaml and docs/DEPLOY.md.
PUBLIC_MODE = os.getenv("PUBLIC_MODE", "false").strip().lower() in ("1", "true", "yes", "on")
# Disables the "point at a local path" field entirely when true - that field
# lets the caller make THIS SERVER read an arbitrary file from its own disk,
# which is fine for a single trusted local user and unsafe on a public site.
LOCAL_PATH_ENABLED = os.getenv("LOCAL_PATH_ENABLED", "false" if PUBLIC_MODE else "true").strip().lower() in ("1", "true", "yes", "on")
# 0 = unlimited. Duration is checked cheaply (container metadata only) before
# any transcription work starts.
MAX_VIDEO_SECONDS = int(os.getenv("MAX_VIDEO_SECONDS", "1200" if PUBLIC_MODE else "0"))
# 0 = unlimited. Extra jobs beyond this are rejected with a "busy" message
# rather than silently queued forever on a tiny free-tier CPU.
MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "1" if PUBLIC_MODE else "0"))
# 0 = unlimited. Simple in-memory per-IP cap on new jobs per hour.
RATE_LIMIT_PER_HOUR = int(os.getenv("RATE_LIMIT_PER_HOUR", "6" if PUBLIC_MODE else "0"))
