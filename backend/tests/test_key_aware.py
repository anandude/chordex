"""A2.1: key-conditioned Viterbi transitions (pure-logic tests, no audio)."""

import numpy as np

from chord_engine.template_engine import (
    _CHORD_NAMES,
    _N_CHORDS,
    _key_aware_enabled,
    _key_aware_transitions,
    _viterbi,
)
from postprocess import key_from_chroma


def _idx(name: str) -> int:
    return _CHORD_NAMES.index(name)


def test_unknown_key_falls_back_to_none():
    assert _key_aware_transitions("unknown") is None
    assert _key_aware_transitions("") is None
    assert _key_aware_transitions("C dorian") is None
    assert _key_aware_transitions(None) is None  # type: ignore[arg-type]


def test_matrix_shape_and_self_bias():
    m = _key_aware_transitions("C major")
    assert m is not None
    assert m.shape == (_N_CHORDS, _N_CHORDS)
    # Self-transitions stay the strongest in every row.
    assert bool((np.diag(m) >= m.max(axis=1)).all())


def test_diatonic_preferred_over_chromatic():
    m = _key_aware_transitions("C major")
    assert m is not None
    c, f, fs = _idx("C"), _idx("F"), _idx("F#")
    assert m[c, f] > m[c, fs]  # F diatonic in C, F# is not


def test_relative_major_minor_nudge():
    m = _key_aware_transitions("C major")
    assert m is not None
    # Same target root, major quality wins in a major key — compared from a
    # *third* state, since staying put always dominates its own row by design.
    assert m[_idx("G"), _idx("C")] > m[_idx("G"), _idx("Cm")]
    m_min = _key_aware_transitions("A minor")
    assert m_min is not None
    assert m_min[_idx("E"), _idx("Am")] > m_min[_idx("E"), _idx("A")]


def test_n_target_neutral():
    m = _key_aware_transitions("G major")
    assert m is not None
    n = _idx("N")
    col = m[:, n].copy()
    col[n] = 0.0  # N->N self-transition keeps self_bias; moves to N are neutral
    assert col.max() == 0.0


def test_viterbi_accepts_custom_matrix():
    rng = np.random.default_rng(0)
    log_emission = np.log(rng.random((20, _N_CHORDS)) + 1e-12)
    path_plain = _viterbi(log_emission, self_bias=3.0)
    assert len(path_plain) == 20
    m = _key_aware_transitions("C major")
    path_keyed = _viterbi(log_emission, self_bias=3.0, log_trans=m)
    assert len(path_keyed) == 20
    # Uniform matrix via None matches an explicitly uniform matrix.
    uni = np.full((_N_CHORDS, _N_CHORDS), 0.0)
    np.fill_diagonal(uni, 3.0)
    assert (path_plain == _viterbi(log_emission, self_bias=3.0, log_trans=uni)).all()


def test_key_from_chroma_profiles():
    from postprocess import _MAJOR_PROFILE, _MINOR_PROFILE

    assert key_from_chroma(_MAJOR_PROFILE) == "C major"
    assert key_from_chroma(_MINOR_PROFILE) == "C minor"
    assert key_from_chroma(np.zeros(12)) == "unknown"


def test_key_aware_env_gate(monkeypatch):
    monkeypatch.delenv("KEY_AWARE", raising=False)
    assert _key_aware_enabled() is False
    monkeypatch.setenv("KEY_AWARE", "1")
    assert _key_aware_enabled() is True
