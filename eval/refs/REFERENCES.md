# Reference files for the benchmark (`eval/bench.json`)

Without these, `eval/run_eval.py` still measures every timing, but lyrics
accuracy (CER/WER), chord placement and word timing show `-` in
`eval/timing.md` ("not measurable"). One set per song id.

| File | What | How to make it |
|---|---|---|
| `<id>.txt` | Lyrics, native script, one sung line per line, in sung order (repeat choruses as sung) | Type or paste, then correct by ear. |
| `<id>.cho` | ChordPro sheet: the chord goes **right before the syllable where it changes** | See the example below. At least 2 verses + 1 chorus, in song order. |
| `<id>.onsets.txt` *(optional)* | ~20 hand-marked word starts | Audacity → Label track → mark word onsets → *Export Labels* (`start<TAB>end<TAB>word`). |

Song ids: `hi_chahun`, `ml_mazha`, `en_elvis` (add more in `eval/bench.json`).

## ChordPro example

```
{comment: Verse 1}
[D]Wise [F#m]men [Bm]say
[G]only [D]fools [A]rush in
but [G]I [A]can't [Bm]help
[G]falling in [D]love [A]with [D]you
```

- A chord mid-word marks the syllable: `beau[G]tiful`.
- Lines with only chords (`[G] [D]`) are instrumental and not scored.
- Use the chord names you'd play; spelling differences don't matter, because
  placement is scored on *position* (which word carries a change).

Then run, from the repo root:

```
backend/.venv/bin/python eval/run_eval.py --tag <name>
```
