"""Eval placement metric (eval/score_placement.py) — guards the yardstick."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "eval"))

from score_placement import onset_mae_ms, parse_chordpro, placement_accuracy  # noqa: E402


def _sheet(words_with_chords):
    return {"rows": [{"kind": "line", "words": [
        {"text": w, "segs": [{"chord": 0 if c else None, "text": w}]}
        for w, c in words_with_chords]}]}


def test_parse_chordpro_marks_words_and_skips_instrumental():
    ref = parse_chordpro("{title: x}\n[G] [D]\n[Am]wise men [F]say\nonly [G] fools")
    assert [(r["word"], r["chord"]) for r in ref] == [
        ("wise", True), ("men", False), ("say", True), ("only", False), ("fools", True)]


def test_placement_perfect_and_off_by_one():
    cho = "[C]wise men [G]say only"
    good = _sheet([("wise", 1), ("men", 0), ("say", 1), ("only", 0)])
    early = _sheet([("wise", 1), ("men", 1), ("say", 0), ("only", 0)])
    assert placement_accuracy(cho, good)["recall"] == 1.0
    r = placement_accuracy(cho, early)
    assert r["recall"] == 0.5 and r["recall_within1"] == 1.0 and r["precision"] == 0.5


def test_placement_partial_ref_and_asr_error():
    cho = "[C]wise men [G]say"
    hyp = _sheet([("intro", 0), ("wise", 1), ("man", 0), ("say", 1), ("outro", 1)])
    r = placement_accuracy(cho, hyp)
    assert r["recall"] == 1.0 and r["precision"] == 1.0  # outro outside ref span


def test_onset_mae():
    words = [{"word": "wise", "timestamp": 1.1}, {"word": "men", "timestamp": 2.0}]
    r = onset_mae_ms("1.0\t1.2\twise\n2.2\t2.4\tmen\n9\t9\tnope", words)
    assert r == {"mae_ms": 150, "matched": 2, "n_ref": 3}
