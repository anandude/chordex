"""
pipeline/sheet.py
-----------------
The chord sheet: one tested place that decides which lyric word (or syllable)
each chord change sits on. Pure and deterministic — no I/O, no models — so the
API can build it whenever both the chord and lyrics results exist.

Output (``version`` 1), ChordPro-like. Chords are referenced by INDEX into the
chord list, so client-side transpose / Easy Mode (which map chords 1:1 and
keep timing) only relabel — positions never need recomputing::

    {"version": 1, "beat": 0.48, "rows": [
      {"kind": "section", "t": 0.0, "label": "INTRO"},
      {"kind": "bars", "t": 0.0, "end": 7.7, "chords": [0, 1], "beats": [8, 8]},
      {"kind": "line", "t": 12.4, "end": 15.9, "carry": 2, "chorus": false,
       "words": [{"text": "beautiful", "t": 13.1, "end": 13.9,
                  "segs": [{"chord": null, "text": "beau"},
                           {"chord": 4, "text": "tiful"}]}],
       "gaps": [{"after_word": 0, "chords": [5]}]}]}

Placement rules (B = beat period, from the beat grid; 0.5 s if unknown):
  1. A change at time t goes on the word whose ONSET is nearest, if within
     ±B/2 (ties → the later word: singers anticipate the beat).
  2. Otherwise, if t falls inside a word that has syllable split points
     (from forced alignment), on the nearest split within ±B/2 — mid-word.
  3. Otherwise it is a GAP slot after the word it follows (a change during a
     held note or a pause), or before the first word.
  4. Changes between lines: shortly before a line (lead-in) → its first word;
     otherwise a gap slot at the end of the previous line when the pause is
     short, or an instrumental ``bars`` row when it is long (≥ 8 beats and
     ≥ 4 s), with INTRO / INSTRUMENTAL / OUTRO section rows.
  5. ``carry`` = the chord already sounding when a line starts without a
     change on its first word, so the player knows what to hold.
  6. ``N`` (no chord) is never placed.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

SHEET_VERSION = 1
_DEFAULT_BEAT = 0.5
_LINE_GAP_MIN = 0.55
_MAX_LINE_CHARS = 42
_LONG_GAP_BEATS = 8
_LONG_GAP_MIN_S = 4.0
_BARS_ROW_BEATS = 16
_MIN_MIDWORD_S = 0.35


# ── helpers ───────────────────────────────────────────────────────────────

def beat_period(beats: list[float] | None, tempo: float | None) -> float:
    if beats and len(beats) >= 4:
        diffs = sorted(b - a for a, b in zip(beats, beats[1:]) if b > a)
        if diffs:
            b = diffs[len(diffs) // 2]
            return round(min(1.5, max(0.25, b)), 3)
    if tempo and tempo > 0:
        return round(min(1.5, max(0.25, 60.0 / tempo)), 3)
    return _DEFAULT_BEAT


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFC", text).lower()
    return re.sub(r"[^\w\s]", "", text).strip()


def _w_end(w: dict[str, Any]) -> float:
    return float(w.get("end", w["timestamp"]) or w["timestamp"])


def _group_words(words: list[dict[str, Any]], lines: list[dict[str, Any]] | None,
                 B: float) -> list[list[int]]:
    """Word index groups, one per lyric line.

    Priority: aligned lines (w0/w1), then lines whose word counts match the
    word list (LRCLIB text), then pause/length grouping.
    """
    n = len(words)
    if lines and all("w0" in l and "w1" in l for l in lines):
        groups = [list(range(int(l["w0"]), int(l["w1"]) + 1)) for l in lines]
        if groups and all(0 <= i < n for g in groups for i in g):
            return [g for g in groups if g]
    if lines:
        counts = [len(str(l.get("text", "")).split()) for l in lines]
        if sum(counts) == n and all(counts):
            out, k = [], 0
            for c in counts:
                out.append(list(range(k, k + c)))
                k += c
            return out
    gap = min(1.0, max(_LINE_GAP_MIN, 0.75 * B))
    groups: list[list[int]] = []
    for i, w in enumerate(words):
        if groups:
            cur = groups[-1]
            pause = float(w["timestamp"]) - _w_end(words[cur[-1]])
            chars = sum(len(words[j]["word"]) + 1 for j in cur) + len(w["word"])
            if pause <= gap and (chars <= _MAX_LINE_CHARS or pause <= 0.15
                                 and chars <= _MAX_LINE_CHARS + 14):
                cur.append(i)
                continue
        groups.append([i])
    return groups


def _place_in_line(t: float, words: list[dict[str, Any]], B: float
                   ) -> tuple[str, int, int]:
    """→ ("word", word_idx, char_idx) or ("gap", after_word_idx, 0)."""
    tol = B / 2
    # rule 1: nearest onset within ±B/2, ties → later word
    best, best_d = None, None
    for k, w in enumerate(words):
        d = abs(float(w["timestamp"]) - t)
        if d <= tol + 1e-9 and (best_d is None or d <= best_d):
            best, best_d = k, d
    if best is not None:
        return ("word", best, 0)
    # rule 2: inside a long-enough word → nearest syllable split
    for k, w in enumerate(words):
        s, e = float(w["timestamp"]), _w_end(w)
        if s <= t < e:
            if e - s >= _MIN_MIDWORD_S:
                splits = [sp for sp in (w.get("splits") or [])
                          if abs(float(sp["t"]) - t) <= tol]
                if splits:
                    sp = min(splits, key=lambda x: abs(float(x["t"]) - t))
                    return ("word", k, int(sp["i"]))
            return ("gap", k, 0)  # change during a held note
    # rule 3: in a pause → gap slot after the preceding word
    after = -1
    for k, w in enumerate(words):
        if float(w["timestamp"]) <= t:
            after = k
    return ("gap", after, 0)


def _segs(text: str, anchors: list[tuple[int, int]]) -> list[dict[str, Any]]:
    """Split a word into segments at chord anchors [(char_idx, chord_idx)]."""
    if not anchors:
        return [{"chord": None, "text": text}]
    anchors = sorted(anchors)
    segs: list[dict[str, Any]] = []
    if anchors[0][0] > 0:
        segs.append({"chord": None, "text": text[:anchors[0][0]]})
    for n, (ci, chord) in enumerate(anchors):
        nxt = anchors[n + 1][0] if n + 1 < len(anchors) else len(text)
        segs.append({"chord": chord, "text": text[ci:nxt]})
    return segs


def _bars_rows(idx: list[int], chords: list[dict[str, Any]], B: float
               ) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cur: list[int] = []
    cur_beats: list[int] = []
    for i in idx:
        c = chords[i]
        n = max(1, round((float(c.get("end", c["timestamp"] + B)) - float(c["timestamp"])) / B))
        gap = (float(c["timestamp"]) - float(chords[cur[-1]].get("end", 0))) if cur else 0
        if cur and (sum(cur_beats) + n > _BARS_ROW_BEATS or gap > 4.0):
            rows.append(_bars(cur, cur_beats, chords))
            cur, cur_beats = [], []
        cur.append(i)
        cur_beats.append(n)
    if cur:
        rows.append(_bars(cur, cur_beats, chords))
    return rows


def _bars(cur: list[int], beats: list[int], chords: list[dict[str, Any]]) -> dict[str, Any]:
    return {"kind": "bars", "t": float(chords[cur[0]]["timestamp"]),
            "end": float(chords[cur[-1]].get("end", chords[cur[-1]]["timestamp"])),
            "chords": cur, "beats": beats}


def _active_chord(chords: list[dict[str, Any]], t: float) -> int | None:
    active = None
    for i, c in enumerate(chords):
        if float(c["timestamp"]) <= t + 1e-6:
            active = i
        else:
            break
    if active is not None and chords[active].get("chord") == "N":
        return None
    return active


def _mark_chorus(line_rows: list[dict[str, Any]]) -> None:
    """Lines that recur (≥3 words, same normalised text) form runs; runs of
    ≥2 such lines that appear at least twice are marked chorus."""
    keys = [_norm(" ".join(w["text"] for w in r["words"])) for r in line_rows]
    counts: dict[str, int] = {}
    for k in keys:
        if len(k.split()) >= 3:
            counts[k] = counts.get(k, 0) + 1
    rep = [counts.get(k, 0) >= 2 for k in keys]
    i = 0
    while i < len(line_rows):
        if rep[i]:
            j = i
            while j < len(line_rows) and rep[j]:
                j += 1
            if j - i >= 2:
                for r in line_rows[i:j]:
                    r["chorus"] = True
            i = j
        else:
            i += 1


# ── entry point ───────────────────────────────────────────────────────────

def build_sheet(
    chords: list[dict[str, Any]],
    words: list[dict[str, Any]] | None = None,
    lines: list[dict[str, Any]] | None = None,
    *,
    beats: list[float] | None = None,
    tempo: float | None = None,
) -> dict[str, Any]:
    """Merge chords + lyric timing into sheet rows (see module docstring)."""
    chords = list(chords or [])
    B = beat_period(beats, tempo)
    playable = [i for i, c in enumerate(chords) if c.get("chord") != "N"]

    words = [w for w in (words or []) if str(w.get("word", "")).strip()]
    if not words and lines:  # timed lines only → even split inside each line
        from pipeline.lyrics_lookup import words_even_split

        timed = [l for l in lines if _w_end(l) > float(l["timestamp"])]
        words = words_even_split(timed)
        lines = timed
    if not words:
        rows = _bars_rows(playable, chords, B)
        return {"version": SHEET_VERSION, "beat": B, "rows": rows}

    groups = _group_words(words, lines, B)
    starts = [float(words[g[0]]["timestamp"]) for g in groups]
    ends = [_w_end(words[g[-1]]) for g in groups]
    lead = max(B / 2, 0.35)
    zone_start = [s - lead for s in starts]

    # bucket every playable chord into: pre-first-line, line i, or gap after i
    in_line: list[list[int]] = [[] for _ in groups]
    after_line: list[list[int]] = [[] for _ in groups]
    intro: list[int] = []
    for ci in playable:
        t = float(chords[ci]["timestamp"])
        if t < zone_start[0]:
            intro.append(ci)
            continue
        li = max(i for i in range(len(groups)) if zone_start[i] <= t)
        if t < ends[li] + B / 2:
            in_line[li].append(ci)
        else:
            after_line[li].append(ci)

    rows: list[dict[str, Any]] = []
    if intro:
        if starts[0] - float(chords[intro[0]]["timestamp"]) >= max(
                _LONG_GAP_MIN_S, _LONG_GAP_BEATS * B):
            rows.append({"kind": "section", "t": max(0.0, float(chords[intro[0]]["timestamp"])),
                         "label": "INTRO"})
        rows.extend(_bars_rows(intro, chords, B))

    line_rows: list[dict[str, Any]] = []
    for li, g in enumerate(groups):
        lw = [words[i] for i in g]
        anchors: list[list[tuple[int, int]]] = [[] for _ in lw]
        gaps: dict[int, list[int]] = {}
        for ci in in_line[li]:
            kind, k, char = _place_in_line(float(chords[ci]["timestamp"]), lw, B)
            if kind == "word":
                anchors[k].append((char, ci))
            else:
                gaps.setdefault(k, []).append(ci)
        nxt_start = starts[li + 1] if li + 1 < len(groups) else float("inf")
        pause = nxt_start - ends[li]
        long_gap = pause >= max(_LONG_GAP_MIN_S, _LONG_GAP_BEATS * B)
        tail = after_line[li]
        if tail and not long_gap:
            gaps.setdefault(len(lw) - 1, []).extend(tail)
            tail = []
        first_has = bool(anchors[0] and anchors[0][0][0] == 0) or bool(gaps.get(-1))
        carry = None if first_has else _active_chord(chords, starts[li])
        row = {
            "kind": "line", "t": round(starts[li], 3), "end": round(ends[li], 3),
            "carry": carry, "chorus": False,
            "words": [{"text": w["word"], "t": round(float(w["timestamp"]), 3),
                       "end": round(_w_end(w), 3), "segs": _segs(w["word"], a)}
                      for w, a in zip(lw, anchors)],
            "gaps": [{"after_word": k, "chords": v} for k, v in sorted(gaps.items())],
        }
        rows.append(row)
        line_rows.append(row)
        if tail:
            label = "OUTRO" if li == len(groups) - 1 else "INSTRUMENTAL"
            rows.append({"kind": "section", "t": float(chords[tail[0]]["timestamp"]),
                         "label": label})
            rows.extend(_bars_rows(tail, chords, B))

    _mark_chorus(line_rows)
    # a CHORUS label before each run of chorus lines
    out: list[dict[str, Any]] = []
    prev_chorus = False
    for r in rows:
        is_ch = r.get("kind") == "line" and r.get("chorus")
        if is_ch and not prev_chorus:
            out.append({"kind": "section", "t": r["t"], "label": "CHORUS"})
        if r.get("kind") == "line":
            prev_chorus = bool(is_ch)
        out.append(r)
    return {"version": SHEET_VERSION, "beat": B, "rows": out}
