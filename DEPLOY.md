# Deploying the website (free, no credit card)

This gets `video-transcript-summarizer` onto a public URL using Render's free
tier. No payment info is required for this path.

**Before you start, know the trade-off**: the free tier gives a small shared
CPU and about 512 MB of RAM, with no GPU. Transcription there will be slower
than on your own PC, and files are capped smaller (300 MB / 20 minutes by
default - see `render.yaml`) so the free tier can actually handle them
without crashing or timing out. `outputs/` and `uploads/` are also wiped
every time the service restarts or wakes from sleep - nothing is stored
permanently on the free tier.

## What you need (all free)

1. A **GitHub account** - github.com/signup, no card needed.
2. A **Render account** - render.com/register, no card needed for the free
   web-service plan.

## Steps

### 1. Push this project to GitHub

From a terminal in this folder:

```bash
git init
git add .
git commit -m "Initial commit"
```

Then create a new empty repository at github.com/new (do **not** initialize
it with a README - keep it empty), and push:

```bash
git remote add origin https://github.com/<your-username>/<repo-name>.git
git branch -M main
git push -u origin main
```

`.env` is already excluded from version control by `.gitignore` (check
`.gitignore` still lists `.env` before pushing, so nothing private leaks) -
double-check with `git status` before the first commit that no secrets are
staged.

### 2. Connect Render to that repo

1. Log into [dashboard.render.com](https://dashboard.render.com).
2. Click **New** -> **Blueprint**.
3. Pick the GitHub repo you just pushed. Render will read `render.yaml` in
   this project automatically and set everything up: Docker build, free
   plan, and all the environment variables already listed there.
4. Click **Apply** / **Deploy**. First build takes a few minutes (it's
   downloading and installing faster-whisper, onnxruntime, etc.).
5. Once it says **Live**, Render gives you a URL like
   `https://video-transcript-summarizer.onrender.com` - that's your public
   site.

### 3. Verify it actually works

- Open the URL. You should see the same page as locally, minus the "point at
  a local path" option (correctly hidden in public mode).
- Upload a short (under 20 min) video or audio file and confirm it processes.
- Check `https://<your-url>/health` returns `{"status": "ok"}` - Render uses
  this to know the service is alive.

### Common first-deploy issues

- **Build fails on `opencv`/`onnxruntime` import** - the Dockerfile already
  installs `libgomp1`, `libgl1`, `libglib2.0-0` to cover the usual causes of
  this; if it still fails, the Render build log will show exactly which
  shared library is missing - search "docker `<that library name>` opencv".
- **"Service unhealthy" right after deploy** - the first request has to load
  the Whisper model into memory, which can take longer than Render's default
  health-check grace period on a slow free-tier CPU. Increase Render's health
  check timeout in the dashboard if you see this.
- **Uploads over the limit get rejected** - that's `render.yaml`'s
  `MAX_UPLOAD_BYTES`/`MAX_VIDEO_SECONDS` working as intended on the free
  tier, not a bug. Raise them once you upgrade to a paid instance with more
  RAM/CPU.

## When you're ready to pay for more

Upgrading later (bigger instance, persistent disk, a real GPU elsewhere,
your own domain) is a config change, not a rebuild - the same Docker image
and code work unmodified. Just raise `MAX_UPLOAD_BYTES`/`MAX_VIDEO_SECONDS`
in `render.yaml` (or the Render dashboard) to match the bigger instance.
