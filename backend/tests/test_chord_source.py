"""A4.1: CHORD_SOURCE flag + accompaniment fallback (no audio needed)."""

import importlib.util

import pytest

from chord_detector import _chord_source


def test_chord_source_defaults_to_mix(monkeypatch):
    monkeypatch.delenv("CHORD_SOURCE", raising=False)
    assert _chord_source() == "mix"


def test_chord_source_stem(monkeypatch):
    monkeypatch.setenv("CHORD_SOURCE", "stem")
    assert _chord_source() == "stem"


def test_chord_source_unknown_falls_back_to_mix(monkeypatch):
    monkeypatch.setenv("CHORD_SOURCE", "karaoke")
    assert _chord_source() == "mix"


def test_accompaniment_falls_back_without_demucs(tmp_path):
    # Only meaningful where demucs is absent (CI without ML deps): the stem
    # path must degrade to the mixture instead of raising.
    if importlib.util.find_spec("demucs") is not None:
        pytest.skip("demucs installed — fallback not exercised")
    from pipeline.separation import separate_accompaniment

    src = tmp_path / "song.wav"
    src.write_bytes(b"RIFF-fake")
    assert separate_accompaniment(src) == src
