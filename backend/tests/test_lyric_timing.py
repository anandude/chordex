"""Lyric timing fallbacks: no more 0:00 pile-ups (all-zero lines used to
collapse the chord sheet into detached rows and freeze karaoke)."""

from pipeline.alignment import _lines_lack_timing, align
from pipeline.config import LyricsConfig
from pipeline.lyrics_lookup import spread_lines, words_even_split


def _cfg_no_align() -> LyricsConfig:
    cfg = LyricsConfig.from_env()
    cfg.alignment_enabled = False
    return cfg


def test_spread_lines_even_across_duration():
    lines = spread_lines(["a", "b", "c", "d"], 100.0)
    assert [l["timestamp"] for l in lines] == [0.0, 25.0, 50.0, 75.0]
    assert lines[-1]["end"] == 100.0
    # contiguous, no gaps/overlaps
    for prev, cur in zip(lines, lines[1:]):
        assert cur["timestamp"] == prev["end"]


def test_spread_lines_unknown_duration():
    lines = spread_lines(["a", "b"], None)
    assert lines[0]["timestamp"] == 0.0
    assert lines[1]["timestamp"] == lines[0]["end"] > 0.0


def test_lines_lack_timing():
    assert _lines_lack_timing([]) is True
    assert _lines_lack_timing([{"timestamp": 0.0, "end": 0.0, "text": "x"}]) is True
    assert _lines_lack_timing([{"timestamp": 0.0, "end": 12.5, "text": "x"}]) is False
    assert _lines_lack_timing([
        {"timestamp": 0.0, "end": 0.0, "text": "x"},
        {"timestamp": 9.0, "end": 12.0, "text": "y"},
    ]) is False


def test_even_split_over_spread_lines_covers_song():
    lines = spread_lines(["hello world", "foo bar baz"], 60.0)
    words = words_even_split(lines)
    assert words[0]["timestamp"] == 0.0
    assert words[-1]["end"] == 60.0
    assert len(words) == 5


def test_align_fallback_spreads_untimed_text():
    # Aligner disabled + plain text (the old path crammed every word into
    # [0, 0.3] and left lines at 0:00).
    out = align("/nonexistent.wav", text="hello world foo bar",
                duration=40.0, cfg=_cfg_no_align())
    assert out["backend"] == "even-split"
    words = out["words"]
    assert len(words) == 4
    assert words[0]["timestamp"] == 0.0
    assert words[-1]["end"] == 40.0
    assert all(l["end"] > l["timestamp"] for l in out["lines"])


def test_align_fallback_unknown_duration():
    out = align("/nonexistent.wav", text="hello world",
                duration=None, cfg=_cfg_no_align())
    words = out["words"]
    assert words[0]["timestamp"] == 0.0
    assert words[-1]["timestamp"] > 0.0
