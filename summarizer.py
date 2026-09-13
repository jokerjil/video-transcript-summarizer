"""Fully offline summariser. No API, no key, no external service, no ML model.

Approach: classic extractive summarisation.
  1. Rebuild sentences (with timestamps) from the Whisper segments.
  2. Score sentences with TextRank (a PageRank-style graph over sentence
     similarity) blended with a word-frequency term.
  3. Assemble a Markdown digest: overview, key points, a timestamped
     chapter-by-chapter breakdown, keywords, and stats.

Everything here is deterministic and runs on the local CPU in milliseconds.
"""
from __future__ import annotations

import collections
import math
import re
from typing import Callable, Optional

import config

ProgressFn = Optional[Callable[[float, str], None]]

_STOPWORDS = frozenset("""
a about above after again against all am an and any are arent as at be because been
before being below between both but by can cannot could couldnt did didnt do does
doesnt doing dont down during each few for from further had hadnt has hasnt have
havent having he hed hell hes her here heres hers herself him himself his how hows
i id ill im ive if in into is isnt it its itself lets me more most mustnt my myself
no nor not of off on once only or other ought our ours ourselves out over own same
shant she shed shell shes should shouldnt so some such than that thats the their
theirs them themselves then there theres these they theyd theyll theyre theyve this
those through to too under until up very was wasnt we wed well were weve werent what
whats when whens where wheres which while who whos whom why whys with wont would
wouldnt you youd youll youre youve your yours yourself yourselves just like get got
go going know think really thing things kind lot yeah yep okay ok right actually
basically literally mean say said says gonna wanna sort stuff much many one two also
even still back come came take took make made want need use used using put see saw
look looked way ways time times day days will shall may might able let done another
new old good bad big small first last next thats theres whats lets im ive dont didnt
gonna today tomorrow yesterday everyone everybody something someone anything anyone
""".split())

_TS_RE = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\]\s*(.*)$")
_SENT_END_RE = re.compile(r"[.!?][\"')\]]?\s")
_WORD_RE = re.compile(r"[A-Za-z0-9']+")
_LOWER_WORD_RE = re.compile(r"[a-z0-9']+")


def _hms(seconds: float) -> str:
    total = max(int(round(seconds)), 0)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _parse_rows(transcript: str) -> list:
    """[(start_seconds, text), ...] from the timestamped transcript."""
    rows = []
    for line in transcript.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _TS_RE.match(line)
        if m:
            h, mi, s, text = m.groups()
            rows.append((int(h) * 3600 + int(mi) * 60 + int(s), text.strip()))
        elif rows:  # continuation of a wrapped line
            rows[-1] = (rows[-1][0], (rows[-1][1] + " " + line).strip())
    return rows


def _sentences(rows: list) -> list:
    """Merge short Whisper segments into sentence-ish units, keeping a start time."""
    sents = []
    buf, start = "", None
    for t, text in rows:
        if start is None:
            start = t
        buf = (buf + " " + text).strip()
        while True:
            m = _SENT_END_RE.search(buf)
            if not m:
                break
            cut = m.end()
            piece = buf[:cut].strip()
            if len(piece) >= 3:
                sents.append((start, piece))
            buf = buf[cut:].lstrip()
            start = t
        if len(buf) > 400:  # runaway sentence with no punctuation
            sents.append((start, buf.strip()))
            buf, start = "", None
    if buf.strip():
        sents.append((start or 0, buf.strip()))
    return sents


def _tokens(text: str) -> list:
    return [w for w in _LOWER_WORD_RE.findall(text.lower())
            if len(w) > 2 and w.replace("'", "") not in _STOPWORDS]


def _textrank(token_lists: list, iters: int = 30, damping: float = 0.85) -> list:
    n = len(token_lists)
    if n == 0:
        return []
    if n == 1:
        return [1.0]
    counters = [collections.Counter(tl) for tl in token_lists]
    sim = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            ci, cj = counters[i], counters[j]
            common = set(ci) & set(cj)
            if not common:
                continue
            overlap = sum(ci[w] + cj[w] for w in common)
            norm = math.log(len(token_lists[i]) + 1) + math.log(len(token_lists[j]) + 1)
            if norm:
                sim[i][j] = sim[j][i] = overlap / norm
    row_sums = [sum(r) or 1.0 for r in sim]
    scores = [1.0 / n] * n
    for _ in range(iters):
        scores = [
            (1 - damping) / n
            + damping * sum(sim[j][i] / row_sums[j] * scores[j] for j in range(n) if j != i)
            for i in range(n)
        ]
    return scores


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _dedupe(indices: list, token_sets: list, threshold: float = 0.6) -> list:
    kept = []
    for i in indices:
        if all(_jaccard(token_sets[i], token_sets[k]) < threshold for k in kept):
            kept.append(i)
    return kept


def summarize(timestamped_transcript: str, meta: Optional[dict] = None,
              progress: ProgressFn = None) -> str:
    transcript = (timestamped_transcript or "").strip()
    if not transcript:
        return "_No speech was detected in this file, so there is nothing to summarise._"

    if progress:
        progress(0.15, "Rebuilding sentences")
    rows = _parse_rows(transcript)
    sents = _sentences(rows)
    if not sents:
        return "_The transcript held no usable sentences._"

    token_lists = [_tokens(s) for _, s in sents]
    token_sets = [set(tl) for tl in token_lists]
    content_idx = [i for i, tl in enumerate(token_lists) if len(tl) >= 4]

    total_dur = float((meta or {}).get("duration") or (rows[-1][0] if rows else 0) or sents[-1][0])
    word_count = sum(len(_WORD_RE.findall(s)) for _, s in sents)
    wpm = (word_count / (total_dur / 60)) if total_dur else 0.0

    # Very short transcript: ranking adds nothing.
    if len(content_idx) <= 4:
        body = " ".join(s for _, s in sents)
        return (
            f"## Overview\n\n{body}\n\n"
            f"## Stats\n\n"
            f"- Duration: {_hms(total_dur)}\n"
            f"- Words: {word_count}\n"
            f"- Sentences: {len(sents)}\n"
        )

    if progress:
        progress(0.4, "Scoring sentences (TextRank)")
    sub_scores = _textrank([token_lists[i] for i in content_idx])
    score_by_idx = {content_idx[k]: sub_scores[k] for k in range(len(content_idx))}

    freq = collections.Counter(w for tl in token_lists for w in tl)
    max_f = max(freq.values()) if freq else 1
    norm_f = {w: c / max_f for w, c in freq.items()}
    for i in content_idx:  # blend graph centrality with mean term frequency
        tl = token_lists[i]
        tf = sum(norm_f.get(w, 0.0) for w in tl) / len(tl)
        score_by_idx[i] = 0.7 * score_by_idx[i] * len(content_idx) + 0.3 * tf

    ranked = sorted(content_idx, key=lambda i: score_by_idx[i], reverse=True)

    if progress:
        progress(0.7, "Assembling summary")

    deduped = _dedupe(ranked, token_sets)
    overview_idx = deduped[: config.SUMMARY_SENTENCES]
    overview = " ".join(sents[i][1] for i in sorted(overview_idx))

    kp_idx = deduped[: config.SUMMARY_KEY_POINTS]
    key_points = [sents[i][1] for i in sorted(kp_idx)]

    # Chapters: split the timeline into equal buckets, best 2 sentences each.
    n_chapters = max(2, min(config.SUMMARY_CHAPTERS, len(sents) // 2))
    span = total_dur / n_chapters if total_dur else 0
    chapters = []
    for c in range(n_chapters):
        lo = c * span
        hi = (c + 1) * span if c < n_chapters - 1 else total_dur + 1
        bucket = [i for i in range(len(sents)) if lo <= sents[i][0] < hi]
        if not bucket:
            continue
        pick = sorted(bucket, key=lambda i: score_by_idx.get(i, 0.0), reverse=True)[:2]
        text = " ".join(sents[i][1] for i in sorted(pick))
        chapters.append(f"**[{_hms(lo)} - {_hms(min(hi, total_dur))}]** {text}")

    keywords = [w for w, _ in freq.most_common(15)]
    bigrams: collections.Counter = collections.Counter()
    for tl in token_lists:
        for a, b in zip(tl, tl[1:]):
            bigrams[a + " " + b] += 1
    phrases = [p for p, c in bigrams.most_common(12) if c > 1][:8]

    src = (meta or {}).get("source")
    lang = (meta or {}).get("language")

    out = []
    if src:
        out.append(f"*Source: {src}*")
    out.append("## Overview\n\n" + overview)
    out.append("## Key Points\n\n" + "\n".join(f"- {p}" for p in key_points))
    if chapters:
        out.append("## Chapter by Chapter\n\n" + "\n\n".join(chapters))
    out.append("## Keywords\n\n" + ", ".join(keywords))
    if phrases:
        out.append("## Recurring Phrases\n\n" + ", ".join(phrases))
    stats = [
        f"- Duration: {_hms(total_dur)}",
        f"- Words: {word_count:,}",
        f"- Sentences: {len(sents)}",
        f"- Speaking rate: {wpm:.0f} words/min" if wpm else "",
        f"- Language: {lang}" if lang else "",
    ]
    out.append("## Stats\n\n" + "\n".join(s for s in stats if s))

    if progress:
        progress(1.0, "Summary ready")
    return "\n\n".join(out) + "\n"
