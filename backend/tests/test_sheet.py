"""L2: chord → word placement (pipeline/sheet.py). The easiest thing in the
app to regress, so every rule has a table-driven case here."""

import pytest

from pipeline.sheet import _place_in_line, beat_period, build_sheet

B = 0.5  # beat period used by most cases (120 bpm)
BEATS = [i * B for i in range(400)]


def W(word, t, end=None, splits=None):
    w = {"word": word, "timestamp": t, "end": end if end is not None else t + 0.3}
    if splits:
        w["splits"] = splits
    return w


def C(chord, t, end):
    return {"chord": chord, "timestamp": t, "end": end}


def line_rows(sheet):
    return [r for r in sheet["rows"] if r["kind"] == "line"]


def chords_on(row):
    """{word_text_segment: chord_idx} for quick assertions."""
    out = {}
    for w in row["words"]:
        for s in w["segs"]:
            if s["chord"] is not None:
                out[s["text"]] = s["chord"]
    return out


WORDS = [W("wise", 10.0, 10.4), W("men", 10.5, 10.9), W("say", 11.0, 12.6),
         W("only", 13.0, 13.4), W("fools", 13.5, 13.9)]


@pytest.mark.parametrize("t, expect", [
    (10.0, ("word", 0, 0)),     # exact onset
    (10.2, ("word", 0, 0)),     # 0.2 s late, nearest onset is "wise"
    (10.3, ("word", 1, 0)),     # nearer "men" (0.2) than "wise" (0.3)
    (10.25, ("word", 1, 0)),    # tie → later word (anticipation)
    (12.0, ("gap", 2, 0)),      # inside held "say", no split → after it
    (12.8, ("word", 3, 0)),     # in the pause, 0.2 s before "only"
    (12.7, ("gap", 2, 0)),      # pause, 0.3 s before "only" (> B/2=0.25)
    (9.5, ("gap", -1, 0)),      # before the first word, beyond tolerance
])
def test_place_in_line(t, expect):
    assert _place_in_line(t, WORDS, B) == expect


def test_mid_word_split_point():
    words = [W("beautiful", 5.0, 6.0, splits=[{"i": 4, "t": 5.4}, {"i": 6, "t": 5.7}])]
    assert _place_in_line(5.45, words, B) == ("word", 0, 4)
    assert _place_in_line(5.75, words, B) == ("word", 0, 6)
    sheet = build_sheet([C("C", 5.0, 5.45), C("G", 5.45, 9.0)], words, beats=BEATS)
    segs = line_rows(sheet)[0]["words"][0]["segs"]
    assert segs == [{"chord": 0, "text": "beau"}, {"chord": 1, "text": "tiful"}]


def test_full_line_and_carry():
    chords = [C("G", 8.0, 10.0), C("C", 10.0, 11.0), C("D", 11.0, 13.5),
              C("G", 13.5, 16.0)]
    sheet = build_sheet(chords, WORDS, beats=BEATS)
    row = line_rows(sheet)[0]
    assert chords_on(row) == {"wise": 1, "say": 2, "fools": 3}
    assert row["carry"] is None  # change on the first word
    # the G before the line sits in a short intro (not a section)
    assert sheet["rows"][0]["kind"] == "bars" and sheet["rows"][0]["chords"] == [0]


def test_carry_when_no_change_on_first_word():
    sheet = build_sheet([C("Am", 0.0, 12.0), C("F", 12.0, 20.0)], WORDS, beats=BEATS)
    row = line_rows(sheet)[0]
    assert row["carry"] == 0
    assert row["gaps"] == [{"after_word": 2, "chords": [1]}]  # held "say"


def test_lead_in_chord_lands_on_first_word():
    sheet = build_sheet([C("Em", 9.8, 20.0)], WORDS, beats=BEATS)
    assert chords_on(line_rows(sheet)[0]) == {"wise": 0}


def test_intro_and_instrumental_sections_and_outro():
    l1 = [W("a", 10.0), W("b", 10.5)]
    l2 = [W("c", 30.0), W("d", 30.5)]
    chords = [C("G", 0.0, 4.0), C("D", 4.0, 10.0), C("C", 10.0, 15.0),
              C("Em", 15.0, 22.0), C("D", 22.0, 30.0), C("G", 30.0, 40.0),
              C("C", 40.0, 44.0)]
    sheet = build_sheet(chords, l1 + l2, beats=BEATS)
    kinds = []
    for r in sheet["rows"]:  # collapse consecutive bars rows (16-beat wrap)
        k = (r["kind"], r.get("label"))
        if not (k == ("bars", None) and kinds and kinds[-1] == k):
            kinds.append(k)
    assert kinds == [("section", "INTRO"), ("bars", None), ("line", None),
                     ("section", "INSTRUMENTAL"), ("bars", None), ("line", None),
                     ("section", "OUTRO"), ("bars", None)]
    bars = [r for r in sheet["rows"] if r["kind"] == "bars"]
    assert [b["chords"] for b in bars] == [[0], [1], [3], [4], [6]]
    assert bars[0]["beats"] == [8] and bars[1]["beats"] == [12]


def test_short_pause_chord_becomes_trailing_gap():
    l1 = [W("a", 10.0), W("b", 10.5, 10.8)]
    l2 = [W("c", 13.0), W("d", 13.5)]
    sheet = build_sheet([C("G", 10.0, 11.8), C("D", 11.8, 13.0), C("C", 13.0, 15.0)],
                        l1 + l2, beats=BEATS)
    r1, r2 = line_rows(sheet)
    assert r1["gaps"] == [{"after_word": 1, "chords": [1]}]
    assert chords_on(r2) == {"c": 2}


def test_every_playable_chord_appears_exactly_once_in_order():
    import random

    random.seed(3)
    words, t = [], 2.0
    for i in range(60):
        t += random.choice([0.3, 0.4, 0.6, 1.5, 3.0])
        words.append(W(f"w{i}", t, t + 0.25))
    chords, t = [], 0.0
    while t < words[-1]["end"] + 10:
        d = random.choice([0.5, 1.0, 2.0, 4.0])
        chords.append(C(random.choice(["G", "C", "D", "Em", "N"]), t, t + d))
        t += d
    sheet = build_sheet(chords, words, beats=BEATS)
    seen = []
    for r in sheet["rows"]:
        if r["kind"] == "bars":
            seen += r["chords"]
        elif r["kind"] == "line":
            pos = []  # (order key, chord) — words then gaps in time order
            for k, w in enumerate(r["words"]):
                for s in w["segs"]:
                    if s["chord"] is not None:
                        pos.append(((k, 0), s["chord"]))
            for g in r["gaps"]:
                for c in g["chords"]:
                    pos.append(((g["after_word"], 1), c))
            seen += [c for _, c in sorted(pos)]
    playable = [i for i, c in enumerate(chords) if c["chord"] != "N"]
    assert sorted(seen) == playable          # each exactly once, N never
    assert seen == sorted(seen)              # time order preserved


def test_two_changes_on_one_word():
    words = [W("go", 10.0, 10.3), W("now", 12.0, 12.3)]
    sheet = build_sheet([C("G", 10.0, 10.1), C("D", 10.1, 12.0), C("C", 12.0, 14.0)],
                        words, beats=BEATS)
    segs = line_rows(sheet)[0]["words"][0]["segs"]
    assert [s["chord"] for s in segs] == [0, 1]


def test_chords_only_without_lyrics():
    sheet = build_sheet([C("G", 0, 2), C("N", 2, 3), C("C", 3, 5)], [], beats=BEATS)
    assert [r["kind"] for r in sheet["rows"]] == ["bars"]
    assert sheet["rows"][0]["chords"] == [0, 2]


def test_uses_aligned_line_groups_and_lrclib_line_counts():
    words = [W("a", 1.0), W("b", 1.4), W("c", 1.8), W("d", 2.2)]
    aligned = [{"timestamp": 1.0, "end": 1.7, "text": "a b", "w0": 0, "w1": 1},
               {"timestamp": 1.8, "end": 2.5, "text": "c d", "w0": 2, "w1": 3}]
    assert len(line_rows(build_sheet([C("G", 0, 3)], words, aligned))) == 2
    lrc = [{"timestamp": 1.0, "end": 1.7, "text": "a b c"},
           {"timestamp": 2.2, "end": 2.5, "text": "d"}]
    rows = line_rows(build_sheet([C("G", 0, 3)], words, lrc))
    assert [len(r["words"]) for r in rows] == [3, 1]


def test_timed_lines_without_words_even_split():
    lines = [{"timestamp": 10.0, "end": 12.0, "text": "one two three four"}]
    sheet = build_sheet([C("G", 10.0, 11.0), C("D", 11.0, 12.0)], [], lines, beats=BEATS)
    assert chords_on(line_rows(sheet)[0]) == {"one": 0, "three": 1}


def test_unknown_tempo_defaults_and_beat_estimate():
    assert beat_period(None, None) == 0.5
    assert beat_period(None, 100.0) == 0.6
    assert beat_period([0, 0.4, 0.8, 1.2, 1.6], None) == 0.4


def test_chorus_detection():
    def L(text, t):
        return [W(x, t + 0.3 * i) for i, x in enumerate(text.split())]
    words = (L("verse words here now", 10) + L("love me tender love", 20) +
             L("love me sweet never", 25) + L("other verse stuff here", 40) +
             L("love me tender love", 50) + L("love me sweet never", 55))
    sheet = build_sheet([C("G", 0, 60)], words, beats=BEATS)
    labels = [r["label"] for r in sheet["rows"] if r["kind"] == "section"]
    assert labels.count("CHORUS") == 2
    assert [r["chorus"] for r in line_rows(sheet)] == [False, True, True, False, True, True]


def test_easy_mode_and_transpose_only_relabel():
    """Sheet positions are chord INDICES — relabelling chords (Easy Mode,
    transpose) keeps the same sheet; Easy Mode keeps length and timing."""
    from easy_chords import apply_easy_mode

    chords = [C("Gmaj7", 9.8, 11.0), C("Cadd9", 11.0, 13.5), C("D7", 13.5, 16.0)]
    easy = apply_easy_mode(chords, key="G major")["chords"]
    assert len(easy) == len(chords)
    assert [(c["timestamp"], c["end"]) for c in easy] == [
        (c["timestamp"], c["end"]) for c in chords]
    assert build_sheet(easy, WORDS, beats=BEATS) == build_sheet(chords, WORDS, beats=BEATS)


def test_status_attaches_romanised_sheet(monkeypatch):
    import main

    store = {}
    monkeypatch.setattr(main._redis_kv, "get", lambda k: store.get(k))
    monkeypatch.setattr(main._redis_kv, "setex", lambda k, ttl, v: store.__setitem__(k, v))
    result = {"chords": [C("G", 0.0, 2.0)], "beats": BEATS[:10], "tempo": 120.0,
              "lyrics": [W("मैं", 0.1), W("या", 0.5)], "lyric_lines": [],
              "lyrics_status": "done", "lyrics_language": "hi"}
    main._attach_sheet("j1", result)
    words = line_rows(result["sheet"])[0]["words"]
    assert words[0]["segs"][0]["chord"] == 0
    assert all(w.get("roman") and w["roman"].isascii() for w in words)
    assert "sheet:j1" in store  # final → cached
