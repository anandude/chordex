"""A3: CTC forced alignment core (pure numpy) + syllable split points."""

import numpy as np

from pipeline.alignment import (
    _groups_from_words, _interpolate_missing, _merge_spans, ctc_viterbi, split_points,
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


def test_merge_spans_pads_merges_and_clips():
    spans = [(10.0, 14.0), (15.0, 18.0), (60.0, 64.0)]
    assert _merge_spans(spans, 100.0, pad_s=3.0) == [(7.0, 21.0), (57.0, 67.0)]
    assert _merge_spans([(1.0, 2.0)], 100.0, pad_s=3.0) == [(0.0, 5.0)]


def test_merge_spans_full_pass_when_lyrics_cover_most_of_the_song():
    assert _merge_spans([(0.0, 95.0)], 100.0) is None
    assert _merge_spans([], 100.0) is None


def test_span_emissions_match_full_pass_inside_spans(monkeypatch):
    """Frames inside a span come from the model; frames outside are
    certain-blank and the array keeps the full-song length."""
    import torch

    from pipeline import alignment
    from pipeline.config import LyricsConfig

    vocab = {"-": 0, "a": 1, "b": 2}

    class Model(torch.nn.Module):  # one frame per 320 samples, class = sample sign
        def __init__(self):
            super().__init__()
            self.w = torch.nn.Parameter(torch.zeros(1))

        def forward(self, x):
            fr = x[0, : (x.shape[1] // 320) * 320].reshape(-1, 320).mean(dim=1)
            em = torch.stack([fr * 0, fr, -fr], dim=-1).unsqueeze(0)
            return em, None

    monkeypatch.setattr(alignment, "_get_model", lambda cfg: (Model(), vocab, "cpu", torch))
    y = np.linspace(-1, 1, 60 * alignment.SR, dtype=np.float32)
    cfg = LyricsConfig()
    full, _ = alignment.compute_emissions(y, cfg)
    part, _ = alignment.compute_emissions(y, cfg, spans=[(20.0, 25.0)])
    assert part.shape == full.shape
    inside = slice(int(18 * alignment.FPS), int(27 * alignment.FPS))
    np.testing.assert_allclose(part[inside], full[inside], atol=1e-5)
    assert (part[: int(10 * alignment.FPS)].argmax(axis=1) == 0).all()
