"""Tiny shared helpers."""
from __future__ import annotations

import re


def probe_duration_seconds(media_path) -> float:
    """Cheap media duration probe from container metadata only - no decoding,
    no frame reads. Returns 0.0 if the file can't be probed (never raises)."""
    try:
        import av
        with av.open(str(media_path)) as c:
            if c.duration:
                return float(c.duration) / av.time_base
    except Exception:
        pass
    return 0.0


def hms(seconds: float) -> str:
    total = max(int(round(seconds)), 0)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


_MD_BOLD = re.compile(r"\*\*(.+?)\*\*")


def markdown_to_html(md: str) -> str:
    """Small Markdown subset -> HTML: #-headings, - bullets, **bold**, paragraphs."""
    def esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    out: list[str] = []
    in_list = False
    for raw in esc(md).split("\n"):
        line = _MD_BOLD.sub(r"<strong>\1</strong>", raw)
        h = re.match(r"^(#{1,4})\s+(.*)$", line)
        b = re.match(r"^\s*[-*]\s+(.*)$", line)
        if h:
            if in_list:
                out.append("</ul>")
                in_list = False
            lvl = min(len(h.group(1)) + 1, 4)
            out.append(f"<h{lvl}>{h.group(2)}</h{lvl}>")
        elif b:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{b.group(1)}</li>")
        elif line.strip() == "":
            if in_list:
                out.append("</ul>")
                in_list = False
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<p>{line}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


_HEAD_RE = re.compile(r"^(#{1,4})\s+(.*)$")
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.*)$")
_BOLD_SPLIT_RE = re.compile(r"(\*\*.+?\*\*)")


def iter_md_blocks(md: str):
    """Yield (kind, text) per line of a Markdown subset.

    kind is one of: h1, h2, h3, h4, li, p, blank. `text` still carries any
    **bold** markers untouched - pass it through split_bold() to render them.
    Used by the PDF/Word/plain-structure builders (report.py).
    """
    for raw in (md or "").split("\n"):
        line = raw.rstrip()
        h = _HEAD_RE.match(line)
        b = _BULLET_RE.match(line)
        if h:
            yield f"h{len(h.group(1))}", h.group(2)
        elif b:
            yield "li", b.group(1)
        elif line.strip():
            yield "p", line.strip()
        else:
            yield "blank", ""


def split_bold(text: str):
    """'a **b** c' -> [('a ', False), ('b', True), (' c', False)]."""
    out = []
    for part in _BOLD_SPLIT_RE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            out.append((part[2:-2], True))
        else:
            out.append((part, False))
    return out or [("", False)]
