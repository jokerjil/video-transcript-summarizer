r"""Command-line entry point.

    python cli.py "C:\videos\meeting.mp4"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pipeline


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Transcribe a video/audio file and summarise it, entirely offline."
    )
    ap.add_argument("media", help="Path to a video or audio file")
    ap.add_argument("--stem", help="Base name for the output files")
    args = ap.parse_args()

    src = Path(args.media)
    if not src.is_file():
        sys.exit(f"File not found: {src}")

    def prog(stage: str, frac: float, msg: str) -> None:
        bar_len = 24
        filled = int(bar_len * frac)
        bar = "#" * filled + "-" * (bar_len - filled)
        sys.stderr.write(f"\r[{stage:>10}] |{bar}| {frac * 100:5.1f}%  {msg[:60]:<60}")
        sys.stderr.flush()

    result = pipeline.run(src, progress=prog, out_stem=args.stem)
    sys.stderr.write("\n\n")

    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(result["summary"])
    print()
    print(f"Transcript saved to: {result['transcript_file']}")
    print(f"Summary saved to:    {result['summary_file']}")


if __name__ == "__main__":
    main()
