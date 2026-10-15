"""A3: CTC forced alignment core (pure numpy) + syllable split points."""

import numpy as np

from pipeline.alignment import (
    _groups_from_words, _interpolate_missing, ctc_viterbi, split_points,
)


def _emissions(frames: list[int], C: int = 5, sharp: float = 0.9) -> np.ndarray:
    """Log-probs where frame t strongly prefers class frames[t]."""
    lp = np.full((len(frames), C), (1 - sharp) / (C - 1))
    for t, c in enumerate(frames):
        lp[t, c] = sharp
    return np.log(lp)


def test_viterbi_recovers_token_frames():
    # blank=0; tokens 1,2,3 sung at frames 2-3, 5, 8-9
    em = _emissions([0, 0, 1, 1, 0, 2, 0, 0, 3, 3, 0])
    path = ctc_viterbi(em, [1, 2, 3])
    assert list(path) == [-1, -1, 0, 0, -1, 1, -1, -1, 2, 2, -1]


def test_viterbi_repeated_tokens_need_a_blank():
    em = _emissions([1, 0, 1])
    assert list(ctc_viterbi(em, [1, 1])) == [0, -1, 1]
    assert ctc_viterbi(_emissions([1]), [1, 1]) is None  # cannot fit


def test_viterbi_forces_all_tokens_even_against_evidence():
    em = _emissions([0, 0, 0, 0, 0, 0])
    path = ctc_viterbi(em, [1, 2])
    assert set(path[path >= 0]) == {0, 1}  # both tokens placed, in order
    assert np.all(np.diff(path[path >= 0]) >= 0)


def test_split_points_mid_word_syllables():
    # "beautiful" romanised = itself; char times 0.1 s apart from 1.0 s
    roman = "beautiful"
    pts = split_points("beautiful", roman, [1.0 + 0.1 * i for i in range(len(roman))])
    assert [p["i"] for p in pts] == [4, 6]  # beau|ti|ful
    assert pts[0]["t"] == 1.4


def test_split_points_never_split_indic_vowel_signs():
    native = "अरिञ्जिरुन्निल्ल"  # synthetic Devanagari stand-in with viramas
    roman = "arinyjirunnilla"
    pts = split_points(native, roman, [0.1 * i for i in range(len(roman))])
    import unicodedata
    for p in pts:
        assert not unicodedata.category(native[p["i"]]).startswith("M")
        assert native[p["i"] - 1] != "्"


def test_window_groups_break_on_pauses_and_length():
    words = [{"timestamp": t, "end": t + 0.3, "word": "x"}
             for t in [0.0, 0.5, 1.0, 5.0, 5.4]]
    assert _groups_from_words(words) == [[0, 1, 2], [3, 4]]
    long = [{"timestamp": 0.5 * i, "end": 0.5 * i + 0.4, "word": "x"} for i in range(40)]
    assert all(long[g[-1]]["end"] - long[g[0]]["timestamp"] <= 15.0
               for g in _groups_from_words(long))


def test_interpolate_missing_between_anchors():
    w = [{"timestamp": 1.0, "end": 1.5, "confidence": 0.9},
         {"timestamp": 0.0, "end": 0.0, "confidence": None},
         {"timestamp": 0.0, "end": 0.0, "confidence": None},
         {"timestamp": 3.5, "end": 4.0, "confidence": 0.8}]
    _interpolate_missing(w)
    assert [x["timestamp"] for x in w] == [1.0, 1.5, 2.5, 3.5]
