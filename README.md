# Video Transcript Summarizer

A local app: give it a video (or audio) file up to 8 GB, and it produces

1. a **timestamped transcript**,
2. a **structured summary** (overview, key points, timed chapter breakdown, keywords), and
3. **snapshot frames** grabbed from the video at even intervals.

Everything can be downloaded as **one self-contained document** (summary + snapshots +
transcript in a single HTML file) or as a **ZIP** of every raw file.

Every video is screened for explicit/18+ content **before** transcription starts. If
flagged, the file is rejected on the spot - nothing is transcribed, summarized, or
saved. See [Content moderation](#content-moderation-1) below for exactly how this
works and its real limits.

**Runs 100% offline.** No internet, no API key, no external AI service. Transcription
uses Whisper on your CPU/GPU. The summary is built with a TextRank algorithm in plain
Python. The content check uses NudeNet, whose model ships inside its own package - no
download for that either. The only network access ever made is a one-time download of
the Whisper model file on first run.

---

## Requirements

- **Python 3.9+**
- ~150 MB free disk for the Whisper `base` model on first run (more for larger models)
- No separate FFmpeg install for common formats (`faster-whisper` bundles the decoders)

A CUDA GPU is optional and makes transcription much faster: set `WHISPER_DEVICE=cuda`.

---

## Setup

```bash
cd video-transcript-summarizer
python -m venv .venv
.venv\Scripts\activate            # Windows  (source .venv/bin/activate on macOS/Linux)
pip install -r requirements.txt
```

That is the whole setup. There is nothing to configure.

---

## Use it

### Web UI

```bash
python app.py
```

Open <http://127.0.0.1:5000>. Drag a file in, or paste a full path to a file on this
computer. **For multi-GB files, use the path field** — it skips the upload. The three
stages (transcribe, snapshots, summarize) show progress. When done you get the summary
and a snapshot grid on screen, plus a **Download** dropdown:

| Option | You get |
|---|---|
| **Full document (.html)** | One file: summary, all snapshots (embedded), full transcript. Opens in any browser; print to PDF if you want. |
| **PDF (.pdf)** | Same content as the HTML document, laid out as a printable PDF. Built with `fpdf2` - no Word/LibreOffice/wkhtmltopdf needed. |
| **Word document (.docx)** | Same content again, as an editable `.docx`. Built with `python-docx`. |
| **Everything (.zip)** | Every format above (`.md`, `.txt`, `.html`, `.pdf`, `.docx`) plus `frames/*.jpg` |
| **Summary only (.md)** | Just the summary |
| **Transcript only (.txt)** | Just the transcript |

The PDF export uses fpdf2's built-in fonts, which only cover Latin-1 text. Non-Latin
characters (e.g. Chinese, Arabic, Cyrillic) render as `?` in the PDF only - the HTML,
ZIP, and DOCX exports keep full Unicode.

### Command line

```bash
python cli.py "D:\videos\meeting.mp4"
```

Prints the summary and writes both files to `outputs/`.

---

## What the summary contains

| Section | How it is produced |
|---|---|
| **Overview** | The highest-ranked sentences (TextRank + term frequency), in original order |
| **Key Points** | More ranked sentences, near-duplicates removed |
| **Chapter by Chapter** | Timeline split into equal sections; the top sentences of each, with timestamps |
| **Keywords / Recurring Phrases** | Most frequent content words and word pairs |
| **Stats** | Duration, word count, sentence count, speaking rate |

This is *extractive*: every line in the summary is a real sentence spoken in the
video. It does not paraphrase or invent text, so quality tracks the transcript
quality. For heavy accents or noisy audio, raise `WHISPER_MODEL` to `small` or
`medium`.

---

## Content moderation

Before any transcription happens, a handful of frames are sampled from the video and
run through [NudeNet](https://github.com/notAI-tech/NudeNet), an offline nudity
classifier. Its model file ships inside the `nudenet` package itself, so this makes
**no network call, ever** - same offline guarantee as the rest of the app.

- **If content is flagged**, the job is rejected immediately: transcription never
  starts, no summary is generated, no snapshots are kept, and no files are written to
  `outputs/`. The only trace left is the rejection message shown in the UI.
- **What counts as flagged**: exposed genitals, anus, buttocks, or female breasts,
  above a confidence threshold (`MODERATION_THRESHOLD`, default `0.5`). Ordinary
  content that happens to include skin - swimming, sports, a shirtless person - is
  deliberately *not* flagged; only the classes above are treated as explicit.
- **What this does not cover**: audio-only files (mp3/wav/m4a) skip this check
  entirely - there is no video to sample, and this app has no offline way to screen
  audio content before transcribing it. Extremely brief or off-angle explicit content
  in a long video could also be missed by frame sampling alone.

This is a real, meaningful safety gate - not a certified content-moderation product.
Treat it as a strong default, not an absolute guarantee, and don't rely on it as the
only safeguard if this app is ever used somewhere with untrusted uploaders.

---

## Configuration (optional, via `.env`)

| Key | Default | Notes |
|---|---|---|
| `WHISPER_MODEL` | `base` | `tiny` / `base` / `small` / `medium` / `large-v3` |
| `WHISPER_DEVICE` | `auto` | `cpu` / `cuda` |
| `WHISPER_COMPUTE_TYPE` | `auto` | e.g. `int8` (CPU), `float16` (GPU) |
| `WHISPER_LANGUAGE` | auto-detect | Force with a code like `en` |
| `WHISPER_BEAM_SIZE` | `1` | Decoding beam width. `1` (greedy) is ~1.7x faster than `5` with no measurable accuracy loss in testing; raise it only if you see errors on hard/noisy audio |
| `WHISPER_BATCHED` | `false` | Opt-in extra speed (~25-30% more on top of `beam_size=1`) via batched inference. Trade-off: timestamps become chunky (~30s blocks instead of per-sentence), which coarsens the transcript, Chapter breakdown, and snapshot sync |
| `WHISPER_BATCH_SIZE` | `8` | Batch size when `WHISPER_BATCHED=true` |
| `SUMMARY_SENTENCES` | `7` | Sentences in the Overview |
| `SUMMARY_KEY_POINTS` | `12` | Bullets in Key Points |
| `SUMMARY_CHAPTERS` | `8` | Number of timed sections |
| `SNAPSHOT_COUNT` | `12` | Frames grabbed from the video (`0` disables display snapshots; moderation samples its own frames regardless) |
| `SNAPSHOT_WIDTH` | `640` | Max pixel width per snapshot |
| `MODERATION_ENABLED` | `true` | Set `false` to turn off the explicit-content check entirely |
| `MODERATION_THRESHOLD` | `0.5` | Confidence (`0`-`1`) required to flag a frame. Higher = stricter (fewer false positives, more risk of missing content) |
| `MODERATION_SAMPLE_COUNT` | `10` | Minimum frames sampled for the content check, independent of `SNAPSHOT_COUNT` |
| `MAX_UPLOAD_BYTES` | `8589934592` | Web upload cap (8 GiB) |

---

## Notes and limits

- An 8 GB video can be several hours long. On CPU with the `base` model, expect
  transcription to take a real fraction of the video's runtime; a GPU or a smaller
  model is much faster. The summary step itself is near-instant.
- Uploaded files land in `uploads/` and are deleted after processing. Files given by
  path are read in place and never copied or deleted.
- `outputs/` and `uploads/` are git-ignored.
