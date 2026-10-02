# Validation runbook — turning flags into decisions

Every experiment below follows the same loop: **run baseline → run variant →
compare on the harness → promote or revert**. Primary gate is always `majmin`;
`thirds`/`sevenths` must not regress >1pp; `seg_f`/`n_segments` guard against
flicker wins (accuracy up because boundaries multiplied).

All commands run from `eval/chords/` with backend deps + `mir_eval` installed.

## 0. Baseline rows (do first, once)

```bash
python score_chords.py --manifest manifest.json --run template --tag template
python score_chords.py --manifest manifest.json --run chordino --tag chordino
python calibrate.py --manifest manifest.json --hyps-dir hyps --tag chordino
```

Append both rows to `results.md`. These numbers are the comparison point for
everything below. If a song SKIPs (pending annotation), the means still print
over whatever scored — note the song count in the row.

## A2.2 — key-aware Viterbi (template engine)

```bash
KEY_AWARE=1 python score_chords.py --manifest manifest.json --run template --tag template-keyaware
python score_chords.py --manifest manifest.json --hyps-dir hyps --tag template-keyaware
```

**Promote iff** `majmin` ≥ baseline + 0.02 with no `thirds` regression > 0.01.
Promoting = one-line change in `backend/chord_engine/template_engine.py`
(`_key_aware_enabled` default `"0"` → `"1"`) + a `results.md` row. If neutral
or negative, leave the flag off and note why (e.g. "key estimate unstable on
modulating tracks") — negative results are results.

## A4.2 — accompaniment stem input

```bash
CHORD_SOURCE=stem python score_chords.py --manifest manifest.json --run chordino --tag chordino-stem
CHORD_SOURCE=stem python score_chords.py --manifest manifest.json --run template --tag template-stem
python score_chords.py --manifest manifest.json --hyps-dir hyps --tag chordino-stem
```

Compare **per genre**, never pooled: stem is expected to help dense mixes and
hurt sparse acoustic (separation artifacts). **Promote iff** it wins its
target genre by ≥0.02 majmin without losing elsewhere. Promotion options in
escalating order: per-song heuristic → genre flag → default flip. Also record
wall-time delta (stem pays a demucs run; check the `lyrics_cache`-style
`accompaniment` cache hit rate on repeat runs).

## S4 — chroma frontend grid

```bash
for kind in cens stft; do
  for hop in 2048 4096; do
    CHROMA_KIND=$kind CHROMA_HOP=$hop \
      python score_chords.py --manifest manifest.json --run template --tag template-$kind-$hop
  done
done
```

**Keep a cell iff** faster AND accuracy-neutral-or-better vs the
`template` baseline (majmin within ±0.01 counts as neutral — take the faster).
Time each run with `time` and record wall seconds in the `results.md` notes.
`CHROMA_NN_FILTER=0` is a third axis if cens/stft underperform (their built-in
smoothing may double up with `nn_filter`).

## A3 full run (after annotating the 2 mp3s)

Re-run section 0 over all 4 songs, then per-genre means by hand (synthetic vs
hindi-film vs malayalam-film — the scorer prints pooled means; split them
when reporting). This is the dataset A1 spikes are judged on.

## A1 spike (after the 3 decisions in `docs/btc_decision.md`)

```bash
pip install crema   # verify weights size + TF-vs-torch first, see memo
# then, once crema_engine.py / btc_engine.py exists behind CHORD_ENGINE:
python score_chords.py --manifest manifest.json --run crema --tag crema
python calibrate.py --manifest manifest.json --hyps-dir hyps --tag crema
```

**Keep iff** +pp majmin AND +pp sevenths vs Chordino on our songs, at a wall
time and RAM budget the hosting tier allows (measure peak RSS per song).
