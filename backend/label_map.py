"""
label_map.py
------------
Normalize chord labels from various engines into guitar-friendly notation.

Input formats handled:
  - Chordino / Harte:  "C", "Am", "G:maj", "D:min7", "Bb:maj7", "N", "N.C."
  - MIREX style:       "C:maj", "A:min", "G:7", "F#:dim"
  - Template engine:   already guitar-style

Output: sharps preferred, compact guitar symbols: C, Am, G7, Dm7, Cmaj7, Dsus4, …
"""

from __future__ import annotations

import re

NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

_FLAT_TO_SHARP = {
    "Db": "C#",
    "Eb": "D#",
    "Fb": "E",
    "Gb": "F#",
    "Ab": "G#",
    "Bb": "A#",
    "Cb": "B",
}

# Map quality tokens (after root) → guitar suffix
_QUALITY_MAP = {
    "": "",
    "maj": "",
    "major": "",
    "M": "",
    "min": "m",
    "minor": "m",
    "m": "m",
    "7": "7",
    "maj7": "maj7",
    "M7": "maj7",
    "min7": "m7",
    "m7": "m7",
    "dim": "dim",
    "dim7": "dim7",
    "aug": "aug",
    "+": "aug",
    "sus2": "sus2",
    "sus4": "sus4",
    "sus": "sus4",
    "9": "9",
    "maj9": "maj9",
    "min9": "m9",
    "m9": "m9",
    "6": "6",
    "m6": "m6",
    "add9": "add9",
    "5": "5",
    "hdim7": "m7b5",
    "min7b5": "m7b5",
    "m7b5": "m7b5",
}


def _normalize_root(raw: str) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    # Handle double-char roots first
    if len(raw) >= 2 and raw[1] in "#b":
        root = raw[:2]
        root = _FLAT_TO_SHARP.get(root, root)
        return root if root in NOTES else None
    root = raw[0].upper()
    return root if root in NOTES else None


def normalize_chord(label: str) -> str:
    """
    Convert any common chord label to guitar-friendly form.
    Unknown / no-chord → 'N'.
    """
    if label is None:
        return "N"

    s = str(label).strip()
    if not s or s.upper() in {"N", "NC", "N.C.", "NONE", "X", "SILENCE"}:
        return "N"

    # Chordino sometimes uses "N" with trailing junk
    if s.upper().startswith("N") and len(s) <= 3:
        return "N"

    # Split on colon (Harte / MIREX: "C:min7") or keep as-is
    if ":" in s:
        root_part, quality_part = s.split(":", 1)
    else:
        # e.g. "Am7", "C#maj7", "Bb"
        m = re.match(r"^([A-Ga-g][#b]?)(.*)$", s)
        if not m:
            return "N"
        root_part, quality_part = m.group(1), m.group(2)

    root = _normalize_root(root_part)
    if root is None:
        return "N"

    quality_part = quality_part.strip().replace(" ", "")
    # Strip bass notes after slash: "G/B" → keep G quality, drop slash bass for display simplicity
    # (guitar charts often still show slash; we keep slash if present after quality)
    bass = ""
    if "/" in quality_part:
        quality_part, bass_raw = quality_part.split("/", 1)
        bass_note = _normalize_root(bass_raw)
        if bass_note:
            bass = f"/{bass_note}"

    # Normalize quality tokens
    q_key = quality_part
    # Common variants
    q_key = q_key.replace("major", "maj").replace("minor", "min")
    if q_key not in _QUALITY_MAP:
        # Try lowercased
        q_lower = q_key.lower()
        if q_lower in _QUALITY_MAP:
            q_key = q_lower
        else:
            # Heuristic: leading m / min
            if q_key.startswith("min"):
                rest = q_key[3:]
                suffix = "m" + rest
            elif q_key.startswith("m") and not q_key.startswith("maj"):
                suffix = q_key  # m7, m9, etc.
            elif q_key.startswith("maj"):
                suffix = q_key
            else:
                suffix = q_key
            return root + suffix + bass

    return root + _QUALITY_MAP[q_key] + bass
