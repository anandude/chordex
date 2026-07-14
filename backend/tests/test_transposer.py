"""Unit tests for transposer.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from transposer import (
    transpose_chord,
    transpose_key_label,
    transpose_progression,
)


def test_major_up_two():
    assert transpose_chord("C", 2) == "D"


def test_minor_down_one():
    assert transpose_chord("Am", -1) == "G#m"


def test_quality_preserved():
    assert transpose_chord("Am7", 2) == "Bm7"
    assert transpose_chord("C#maj7", 1) == "Dmaj7"
    assert transpose_chord("Dsus4", 5) == "Gsus4"


def test_flat_normalized():
    assert transpose_chord("Bb", 0) == "A#"
    assert transpose_chord("Bb", 2) == "C"


def test_no_chord():
    assert transpose_chord("N", 5) == "N"


def test_slash_bass_transposed():
    assert transpose_chord("G/B", 2) == "A/C#"


def test_progression():
    chords = [
        {"timestamp": 0.0, "chord": "C", "confidence": 0.9},
        {"timestamp": 2.0, "chord": "Am", "confidence": 0.8},
    ]
    out = transpose_progression(chords, 2)
    assert out[0]["chord"] == "D"
    assert out[1]["chord"] == "Bm"
    assert out[0]["timestamp"] == 0.0
    assert out[0]["confidence"] == 0.9


def test_zero_semitones_identity():
    chords = [{"timestamp": 0.0, "chord": "G"}]
    assert transpose_progression(chords, 0) is chords


def test_key_label():
    assert transpose_key_label("G major", 2) == "A major"
    assert transpose_key_label("A minor", -2) == "G minor"
    assert transpose_key_label("unknown", 3) == "unknown"
