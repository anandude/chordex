#!/usr/bin/env python3
"""Chord-placement + word-onset metrics against hand-made references.

Reference formats
-----------------
ChordPro (``eval/refs/<id>.cho``): lyrics in sung order with each chord placed
immediately before the syllable where it changes::

    [Am]Chahun main [F]ya [G]naa
    tere bi[C]na

Lines starting with ``{`` (directives) or ``#`` are ignored. A chord on its own
(``[G] [D]``) with no lyric is an instrumental marker and is not scored.
Sections may be partial (e.g. verse 1 + chorus) but must keep song order.

Word onsets (``eval/refs/<id>.onsets.txt``): an Audacity label track export,
``start<TAB>end<TAB>word`` per line.

Metrics
-------
placement_accuracy → {"recall", "recall_within1", "precision", "n_ref"}
    Reference words are aligned to our sheet words with a semi-global
    Levenshtein alignment on normalised tokens (free hypothesis prefix/suffix,
    so a partial reference is fine and ASR word errors don't cascade).
    recall          = ref chord markers whose aligned sheet word carries a chord
                      change (on the word or in the gap just before it)
    recall_within1  = same, allowing the change one word early/late
    precision       = sheet chord changes on aligned words that the reference
                      also marks (over the referenced span only)
onset_mae_ms → {"mae_ms", "matched", "n_ref"}
    Each labelled word is matched to the same normalised word in our output
    nearest in time (within 2 s); MAE of start-time differences.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from score import normalize  # noqa: E402

_CHORD = re.compile(r"\[([^\]]+)\]")


def parse_chordpro(text: str) -> list[dict]:
    """→ [{"word": norm_token, "chord": bool}] in order (chord = change on word)."""
    out: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("{", "#")):
            continue
        if not _CHORD.sub("", line).strip():
            continue  # chords-only (instrumental) line
        # Split into whitespace words keeping markers attached to their word.
        for tok in line.split():
            has = bool(_CHORD.search(tok))
            word = normalize(_CHORD.sub("", tok))
            if not word:
                # bare "[G]" between words → belongs to the next word
                if has:
                    out.append({"word": "", "chord": True})
                continue
            for i, w in enumerate(word.split()):
                out.append({"word": w, "chord": has and i == 0})
    # fold empty marker tokens into the following word
    folded: list[dict] = []
    pending = False
    for t in out:
        if not t["word"]:
            pending = True
            continue
        folded.append({"word": t["word"], "chord": t["chord"] or pending})
        pending = False
    return folded


def sheet_words(sheet: dict) -> list[dict]:
    """Flatten a backend sheet into [{"word", "chord": bool}]."""
    out: list[dict] = []
    for row in sheet.get("rows", []):
        if row.get("kind") != "line":
            continue
        gap_before = {g["after_word"] + 1 for g in row.get("gaps", []) if g.get("chord") is not None}
        for wi, w in enumerate(row.get("words", [])):
            has = any(s.get("chord") is not None for s in w.get("segs", [])) or wi in gap_before
            for i, tok in enumerate(normalize(w.get("text", "")).split()):
                out.append({"word": tok, "chord": has and i == 0})
    return out


def _align(ref: list[str], hyp: list[str]) -> list[int | None]:
    """Semi-global alignment: ref fully consumed, hyp prefix/suffix free.
    Returns, per ref index, the aligned hyp index (None if deleted)."""
    n, m = len(ref), len(hyp)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = i
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            sub = dp[i - 1][j - 1] + (0 if ref[i - 1] == hyp[j - 1] else 1)
            dp[i][j] = min(sub, dp[i - 1][j] + 1, dp[i][j - 1] + 1)
    j = min(range(m + 1), key=lambda k: dp[n][k]) if m else 0
    i = n
    mapping: list[int | None] = [None] * n
    while i > 0 and j > 0:
        cost = 0 if ref[i - 1] == hyp[j - 1] else 1
        if dp[i][j] == dp[i - 1][j - 1] + cost:
            mapping[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif dp[i][j] == dp[i - 1][j] + 1:
            i -= 1
        else:
            j -= 1
    return mapping


def placement_accuracy(chordpro: str, sheet: dict, chords: list | None = None) -> dict:
    ref = parse_chordpro(chordpro)
    hyp = sheet_words(sheet)
    if not ref or not hyp:
        return {"recall": None, "recall_within1": None, "precision": None, "n_ref": len(ref)}
    mapping = _align([r["word"] for r in ref], [h["word"] for h in hyp])
    n_ref = sum(r["chord"] for r in ref)
    hit = near = 0
    for ri, r in enumerate(ref):
        if not r["chord"]:
            continue
        hj = mapping[ri]
        if hj is None:
            continue
        if hyp[hj]["chord"]:
            hit += 1
            near += 1
        elif any(0 <= k < len(hyp) and hyp[k]["chord"] for k in (hj - 1, hj + 1)):
            near += 1
    ref_marked = {mapping[ri] for ri, r in enumerate(ref) if r["chord"] and mapping[ri] is not None}
    aligned = [j for j in mapping if j is not None]
    hyp_marked = [j for j in aligned if hyp[j]["chord"]]
    prec = (sum(j in ref_marked for j in hyp_marked) / len(hyp_marked)) if hyp_marked else None
    return {
        "recall": round(hit / n_ref, 3) if n_ref else None,
        "recall_within1": round(near / n_ref, 3) if n_ref else None,
        "precision": round(prec, 3) if prec is not None else None,
        "n_ref": n_ref,
    }


def onset_mae_ms(labels: str, words: list[dict]) -> dict:
    ref = []
    for line in labels.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            try:
                ref.append((float(parts[0]), normalize(parts[2])))
            except ValueError:
                continue
    errs = []
    for t, w in ref:
        cands = [x for x in words if normalize(x.get("word", "")) == w
                 and abs(float(x["timestamp"]) - t) <= 2.0]
        if cands:
            best = min(cands, key=lambda x: abs(float(x["timestamp"]) - t))
            errs.append(abs(float(best["timestamp"]) - t))
    return {
        "mae_ms": round(1000 * sum(errs) / len(errs)) if errs else None,
        "matched": len(errs), "n_ref": len(ref),
    }
