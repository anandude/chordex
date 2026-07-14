"""Unit tests for label_map.normalize_chord"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from label_map import normalize_chord


def test_simple():
    assert normalize_chord("C") == "C"
    assert normalize_chord("Am") == "Am"


def test_harte_mirex():
    assert normalize_chord("C:maj") == "C"
    assert normalize_chord("A:min") == "Am"
    assert normalize_chord("D:min7") == "Dm7"
    assert normalize_chord("G:7") == "G7"
    assert normalize_chord("F#:maj7") == "F#maj7"


def test_no_chord():
    assert normalize_chord("N") == "N"
    assert normalize_chord("N.C.") == "N"
    assert normalize_chord("") == "N"
    assert normalize_chord(None) == "N"  # type: ignore[arg-type]


def test_flats():
    assert normalize_chord("Bb") == "A#"
    assert normalize_chord("Eb:min") == "D#m"


def test_sus_dim_aug():
    assert normalize_chord("D:sus4") == "Dsus4"
    assert normalize_chord("B:dim") == "Bdim"
    assert normalize_chord("C:aug") == "Caug"
