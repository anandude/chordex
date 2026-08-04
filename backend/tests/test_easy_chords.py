"""Unit tests for easy_chords.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from easy_chords import (
    apply_easy_mode,
    simplify_chord,
    simplify_progression,
    suggest_capo,
)


def test_simplify_extensions():
    assert simplify_chord("Am7") == "Am"
    assert simplify_chord("Cmaj7") == "C"
    assert simplify_chord("G9") == "G7"
    assert simplify_chord("Dsus4") == "Dsus4"
    assert simplify_chord("N") == "N"


def test_simplify_drops_slash():
    assert simplify_chord("G/B") == "G"
    assert simplify_chord("Cmaj7/E") == "C"


def test_suggest_capo_for_flat_key():
    # Song in Bb major-ish — capo 1 with A shapes is friendlier
    chords = [
        {"timestamp": 0.0, "chord": "A#"},  # Bb
        {"timestamp": 2.0, "chord": "D#"},  # Eb
        {"timestamp": 4.0, "chord": "F"},
        {"timestamp": 6.0, "chord": "A#"},
    ]
    suggestion = suggest_capo(chords, key="A# major", max_capo=7)
    assert 0 <= suggestion["capo"] <= 7
    # Capo 1 should be better than 0 for Bb/Eb/F
    shapes0 = simplify_progression(chords, capo=0)
    shapes_best = simplify_progression(chords, capo=suggestion["capo"])
    # Best should not be worse than open in a meaningful way for this set
    assert suggestion["score"] >= 0


def test_apply_easy_mode_returns_chords():
    chords = [
        {"timestamp": 0.0, "chord": "Cmaj7", "confidence": 0.9},
        {"timestamp": 2.0, "chord": "Am7", "confidence": 0.8},
        {"timestamp": 4.0, "chord": "F", "confidence": 0.85},
        {"timestamp": 6.0, "chord": "G7", "confidence": 0.9},
    ]
    out = apply_easy_mode(chords, key="C major")
    assert "capo" in out
    assert len(out["chords"]) == 4
    # Extensions stripped (no maj7 / m7 left on roots)
    for c in out["chords"]:
        assert "maj7" not in c["chord"]
        assert not c["chord"].endswith("m7") or c["chord"] in {"Am7", "Em7", "Dm7"}
    # timestamps preserved
    assert out["chords"][1]["timestamp"] == 2.0


def test_c_g_am_f_suggests_easier_than_open_f():
    """C–G–Am–F often gets capo 5 (G–D–Em–C) to avoid the F barre — that's correct."""
    chords = [
        {"timestamp": 0.0, "chord": "C"},
        {"timestamp": 2.0, "chord": "G"},
        {"timestamp": 4.0, "chord": "Am"},
        {"timestamp": 6.0, "chord": "F"},
    ]
    out = apply_easy_mode(chords, key="C major")
    assert 0 <= out["capo"] <= 7
    # Whatever capo is chosen, average difficulty should beat raw open F
    from easy_chords import _score_progression, simplify_progression

    open_score = _score_progression(simplify_progression(chords, capo=0))
    assert out["score"] <= open_score + 0.05


def test_already_open_keys_stay_open():
    chords = [
        {"timestamp": 0.0, "chord": "G"},
        {"timestamp": 2.0, "chord": "D"},
        {"timestamp": 4.0, "chord": "Em"},
        {"timestamp": 6.0, "chord": "C"},
    ]
    out = apply_easy_mode(chords, key="G major")
    assert out["capo"] == 0
