"""
easy_chords.py
--------------
Beginner-friendly chord simplification + capo suggestion.

Pure music theory — no audio reprocessing.

Public API:
    simplify_chord(chord: str) -> str
    simplify_progression(chords, capo=0) -> list[dict]
    suggest_capo(chords, key=None) -> dict
    apply_easy_mode(chords, key=None) -> dict
"""

from __future__ import annotations

from typing import Any

from transposer import NOTES, transpose_chord, transpose_key_label, _parse_chord

# Open / beginner-friendly shapes on guitar (no capo)
_EASY_MAJOR = {"C", "G", "D", "A", "E"}
_EASY_MINOR = {"Am", "Em", "Dm"}  # Bm is barre-ish for beginners
_EASY_OTHER = {
    "C7",
    "G7",
    "D7",
    "A7",
    "E7",
    "B7",
    "Am7",
    "Em7",
    "Dm7",
    "Asus2",
    "Asus4",
    "Dsus2",
    "Dsus4",
    "Esus4",
    "Cadd9",
    "Gsus4",
}

# Quality stripping rules → beginner triad / simple form
_STRIP_RULES: list[tuple[str, str]] = [
    # longest match first
    ("maj13", ""),
    ("maj11", ""),
    ("maj9", ""),
    ("maj7", ""),
    ("m11", "m"),
    ("m13", "m"),
    ("m9", "m"),
    ("m7b5", "m"),
    ("m7", "m"),
    ("min7", "m"),
    ("min", "m"),
    ("dim7", "dim"),
    ("add9", ""),
    ("add11", ""),
    ("sus2", "sus2"),  # keep sus — still open-friendly often
    ("sus4", "sus4"),
    ("sus", "sus4"),
    ("11", "7"),
    ("13", "7"),
    ("9", "7"),
    ("6", ""),
    ("aug", "aug"),
    ("dim", "dim"),
    ("5", ""),  # power → major triad for beginners
    ("7", "7"),  # keep dominant 7 (open-friendly)
    ("m", "m"),
]


def simplify_chord(chord: str) -> str:
    """
    Strip extensions / complex qualities toward beginner forms.
    Preserves slash bass only if the simplified form is still simple.
    'N' unchanged.
    """
    if not chord or chord == "N":
        return "N"

    root, quality, bass = _parse_chord(chord)
    if root not in NOTES:
        return chord

    q = quality
    # Normalize a few aliases
    q = q.replace("major", "maj").replace("minor", "min")
    if q.startswith("min") and not q.startswith("min7"):
        q = "m" + q[3:]
    elif q.startswith("min7"):
        q = "m7" + q[4:]

    simplified_q = q
    for token, replacement in _STRIP_RULES:
        if q == token or q.startswith(token):
            # prefer exact or prefix for compound like m7add9
            if q == token or (q.startswith(token) and token not in ("m", "7", "5")):
                simplified_q = replacement
                break
            if q.startswith(token) and token in ("m7", "maj7", "m9", "9", "11", "13"):
                simplified_q = replacement
                break

    # bare major
    if simplified_q in ("maj", "M", ""):
        simplified_q = ""

    result = root + simplified_q
    # Drop slash bass for easy mode (harder to finger + confuses beginners)
    # Exception: keep if it's a common open inversion? We drop for simplicity.
    return result


def _shape_difficulty(chord: str) -> float:
    """
    Lower is easier. Used to score capo positions.
    0 = open beginner shape, higher = harder / barre-ish.
    """
    if chord == "N":
        return 0.0
    simple = simplify_chord(chord)
    root, quality, _ = _parse_chord(simple)
    label = root + quality

    if label in _EASY_MAJOR or label in _EASY_MINOR or label in _EASY_OTHER:
        return 0.0
    if quality in ("", "m", "7", "m7", "sus2", "sus4") and root in _EASY_MAJOR:
        return 0.2
    # Common barre shapes
    if root in {"F", "A#", "D#", "G#", "C#"} and quality in ("", "m", "7", "m7"):
        return 2.5
    if label in {"Bm", "F#m", "C#m", "G#m", "D#m", "F#", "B"}:
        return 2.0
    # Everything else moderately hard
    return 1.5


def _score_progression(chords: list[dict[str, Any]]) -> float:
    if not chords:
        return 0.0
    total = 0.0
    for c in chords:
        total += _shape_difficulty(c.get("chord", "N"))
    return total / max(len(chords), 1)


def transpose_shapes_down(chords: list[dict[str, Any]], capo: int) -> list[dict[str, Any]]:
    """
    With capo on `capo`, shapes sound `capo` semitones higher.
    So written shapes = original sounding chords transposed down by capo.
    """
    if capo <= 0:
        return [{**c, "chord": c["chord"]} for c in chords]
    return [
        {**c, "chord": transpose_chord(c["chord"], -capo)} for c in chords
    ]


def simplify_progression(
    chords: list[dict[str, Any]],
    *,
    capo: int = 0,
    strip_extensions: bool = True,
) -> list[dict[str, Any]]:
    """
    Optionally map to capo shapes, then strip extensions.
    """
    shaped = transpose_shapes_down(chords, capo)
    if not strip_extensions:
        return shaped
    out = []
    for c in shaped:
        item = {**c, "chord": simplify_chord(c["chord"])}
        out.append(item)
    return out


def suggest_capo(
    chords: list[dict[str, Any]],
    key: str | None = None,
    max_capo: int = 7,
) -> dict[str, Any]:
    """
    Find capo fret 0–max_capo that minimises average shape difficulty
    after simplifying extensions.

    Returns:
        {
          "capo": int,
          "score": float,          # lower = easier
          "easy_key": str | None,  # sounding key of the shapes (if key given)
          "reason": str,
        }
    """
    if not chords:
        return {
            "capo": 0,
            "score": 0.0,
            "easy_key": key,
            "reason": "No chords to analyse",
        }

    best_capo = 0
    best_score = float("inf")
    best_shapes: list[dict[str, Any]] = []

    for capo in range(0, max_capo + 1):
        shapes = simplify_progression(chords, capo=capo, strip_extensions=True)
        score = _score_progression(shapes)
        # slight preference for lower capo when scores tie
        score += capo * 0.02
        if score < best_score:
            best_score = score
            best_capo = capo
            best_shapes = shapes

    easy_key = None
    if key:
        # Shapes are written as if capo=0; sounding key = shape key + capo
        # If original key is the sounding key, shape key = original - capo
        easy_key = transpose_key_label(key, -best_capo) if best_capo else key

    open_count = sum(
        1 for c in best_shapes if _shape_difficulty(c["chord"]) < 0.5
    )
    reason = (
        f"Capo {best_capo}: {open_count}/{len(best_shapes)} shapes are open/easy"
        if best_capo
        else "Open position works well — no capo needed"
    )

    return {
        "capo": best_capo,
        "score": round(best_score, 3),
        "easy_key": easy_key,
        "reason": reason,
    }


def apply_easy_mode(
    chords: list[dict[str, Any]],
    key: str | None = None,
    max_capo: int = 7,
) -> dict[str, Any]:
    """
    Full easy-mode package for a progression.
    """
    suggestion = suggest_capo(chords, key=key, max_capo=max_capo)
    capo = int(suggestion["capo"])
    easy_chords = simplify_progression(chords, capo=capo, strip_extensions=True)
    return {
        "capo": capo,
        "score": suggestion["score"],
        "easy_key": suggestion.get("easy_key"),
        "reason": suggestion["reason"],
        "chords": easy_chords,
    }
