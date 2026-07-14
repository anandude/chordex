"""
transposer.py
-------------
Chord transposition logic — pure music theory, no audio reprocessing.

Public API:
    transpose_progression(chords: list[dict], semitones: int) -> list[dict]
    transpose_chord(chord: str, semitones: int) -> str
"""

from __future__ import annotations

NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

_FLAT_TO_SHARP: dict[str, str] = {
    "Db": "C#",
    "Eb": "D#",
    "Fb": "E",
    "Gb": "F#",
    "Ab": "G#",
    "Bb": "A#",
    "Cb": "B",
}


def _normalize_root(raw: str) -> str | None:
    if not raw:
        return None
    if len(raw) >= 2 and raw[1] in ("#", "b"):
        root = _FLAT_TO_SHARP.get(raw[:2], raw[:2])
        return root if root in NOTES else None
    root = raw[0].upper() if raw else ""
    return root if root in NOTES else None


def _parse_chord(chord: str) -> tuple[str, str, str | None]:
    """
    Split a chord string into (root, quality, bass_or_none).

    Examples
    --------
    'Am7'    -> ('A',  'm7',   None)
    'C#maj7' -> ('C#', 'maj7', None)
    'Bb'     -> ('A#', '',     None)
    'G/B'    -> ('G',  '',     'B')
    'N'      -> ('N',  '',     None)
    """
    if chord == "N":
        return "N", "", None

    bass: str | None = None
    body = chord
    if "/" in chord:
        body, bass_raw = chord.split("/", 1)
        bass = _normalize_root(bass_raw)

    if len(body) >= 2 and body[1] in ("#", "b"):
        raw_root = body[:2]
        quality = body[2:]
    else:
        raw_root = body[0]
        quality = body[1:]

    root = _FLAT_TO_SHARP.get(raw_root, raw_root)
    return root, quality, bass


def transpose_chord(chord: str, semitones: int) -> str:
    """
    Transpose a single chord string by `semitones` half-steps.

    Preserves chord quality (e.g. 'm7', 'maj7', 'sus4') and slash bass notes.
    Passes 'N' (no chord) through unchanged.
    """
    if chord == "N":
        return "N"

    root, quality, bass = _parse_chord(chord)

    if root not in NOTES:
        return chord

    new_root = NOTES[(NOTES.index(root) + semitones) % 12]
    result = new_root + quality
    if bass and bass in NOTES:
        result += "/" + NOTES[(NOTES.index(bass) + semitones) % 12]
    return result


def transpose_progression(chords: list[dict], semitones: int) -> list[dict]:
    """Transpose every chord in a timestamped progression; other keys preserved."""
    if semitones == 0:
        return chords
    return [
        {**item, "chord": transpose_chord(item["chord"], semitones)} for item in chords
    ]


def transpose_key_label(key: str, semitones: int) -> str:
    """Transpose a key label like 'G major' or 'A minor'."""
    if not key or key == "unknown" or semitones == 0:
        return key
    parts = key.strip().split()
    if not parts:
        return key
    root = _normalize_root(parts[0])
    if root is None or root not in NOTES:
        return key
    new_root = NOTES[(NOTES.index(root) + semitones) % 12]
    rest = " ".join(parts[1:]) if len(parts) > 1 else ""
    return f"{new_root} {rest}".strip()
