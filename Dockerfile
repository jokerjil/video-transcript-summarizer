# Video Transcript Summarizer - container image for hosted deployment.
# Local development does NOT need Docker - just `python app.py` in a venv.
FROM python:3.12-slim

# onnxruntime/ctranslate2 need libgomp for OpenMP at runtime. libgl1 and
# libglib2.0-0 cover a common opencv-python-headless import failure on slim
# Debian images even though it's the "headless" build. The `av` wheel bundles
# its own codec libraries, so no separate ffmpeg install is required.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .
RUN mkdir -p outputs uploads static

ENV PYTHONUNBUFFERED=1 \
    PUBLIC_MODE=true

EXPOSE 5000

# Single worker, multiple threads: job state lives in an in-process dict, so
# every request MUST land on the same process. Do not raise --workers above 1
# without first moving job state to something shared (e.g. Redis).
CMD ["sh", "-c", "gunicorn --workers 1 --threads 8 --timeout 120 --bind 0.0.0.0:${PORT:-5000} app:app"]
