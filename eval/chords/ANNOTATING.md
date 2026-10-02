# Hand-annotating eval songs (A3.2)

The harness is only as honest as its references. One carefully annotated song
beats ten sloppy ones. Budget ~30 min per song (verse + chorus minimum; full
song preferred).

## Setup

1. Open the audio in **Sonic Visualiser** (free) or Audacity with a
   spectrogram + chord layer. Play at 0.5–0.75× speed for fast changes.
2. Keep the song's `.lab` stub open beside it (`eval/chords/refs/*.lab`).
3. Have a guitar/keyboard (or a tuner app) handy for ambiguous bars.

## Label vocabulary

Use Harte syntax — the same set `to_harte()` (`score_chords.py`) accepts:

- Triads first: `C:maj`, `A:min`, `D:dim`, `E:aug`, `G:sus4`, `D:sus2`.
- Add `7` / `maj7` / `min7` **only** when the 7th is clearly audible for the
  whole segment (e.g. `G:7`, `C:maj7`, `D:min7`). When in doubt, use the triad.
- `N` for silence, intros/outros without harmony, and speech-only passages.
- Slash bass when the bass note is clearly not the root and it matters for
  guitar (e.g. `G:maj/B`). Otherwise omit it.
- **Sharps only**: `C#`, `F#`, `G#` — never `Db`/`Gb` (matches `label_map.py`).

## Timing

- One line per chord: `START END LABEL`, seconds with millisecond precision.
- Cover the **full duration** with no gaps and no overlaps; each `END` equals
  the next `START`. The scorer validates this.
- Boundaries on the beat where the harmony audibly changes, not where the
  melody moves. Strums/rhythmic fills inside one harmony stay one segment.

## Verification

```bash
# ref parses + maps cleanly (no mir_eval needed)
python score_chords.py --self-test
# after annotating, sanity-check the file loads:
python -c "import sys; sys.path.insert(0,'.'); from score_chords import load_lab; print(load_lab('refs/<id>.lab')[1][:5])"
```

Delete the stub header comment block once the annotation is complete, add the
song's row to `results.md` after the first scored run, and never edit a ref
to make an engine look better — refs are ground truth, engines move, not them.
