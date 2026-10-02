# Chord eval harness (A3)

Scores estimated chord sequences against hand-verified `.lab` references with
`mir_eval` — the same MIREX-style metrics the literature reports, so our
numbers are comparable and our engine swaps are decided by data, not ears.

## Metrics

| Metric | What it forgives | Use it for |
|---|---|---|
| `root` | everything except the root note | coarse sanity |
| `majmin` | extensions (maj7 vs 7 vs triad) | core progression quality |
| `thirds` | 7ths+ (maj7 vs min7 vs 7 count) | jazz/pop-with-7ths tracks |
| `sevenths` | inversions only | full-vocabulary engines |
| `seg_f` | chord *names* (boundary F only) | over-segmentation check |
| `n_frac` | — | share of audio left as no-chord |
| `n_segments` | — | jumpiness (flicker → many segments) |

Primary gate for engine changes: **majmin** (matches our "playable
progression" promise). `thirds`/`sevenths` matter once A1 lands.

## Label mapping

Both ref and hyp labels pass through `to_harte()` (`score_chords.py`), so the
comparison is always fair. Exact: maj, min, 7, maj7, min7, dim, aug, sus2,
sus4, N, slash bass (`G/B` → `G:maj/B`). Folded to triads: 5/6→maj, m6→min,
9→7, maj9→maj7, m9→min7, add9→maj, dim7/m7b5→dim. Unknown extensions fall back
to the triad family by leading-`m` heuristic (lenient, never crashes).

Refs must use **sharps** (`C#`, `F#`), never flats — matching `label_map.py`.

## Adding a song

1. Put the audio somewhere local (copyrighted songs stay out of git —
   `eval/chords/.gitignore` covers local copies; committed fixtures live in
   `test-assets/`).
2. Write `refs/<id>.lab`: one `START END HARTE_LABEL` triple per line, e.g.
   `0.000 2.000 C:maj`. Cover the full duration; use `N` for silence/intros.
3. Add a manifest entry (`manifest.json`): id, audio path (relative to
   `eval/chords/`), ref, genre, key, source. Never average across genres.
4. Run + append a row to `results.md`.

## Running

```bash
# dependency-free sanity (label mapping + ref parsing — no mir_eval needed)
python score_chords.py --self-test

# full run over the manifest with an engine (needs backend deps + mir_eval)
pip install mir_eval
python score_chords.py --manifest manifest.json --run template --tag template
python score_chords.py --manifest manifest.json --run chordino --tag chordino

# score pre-generated hyps (e.g. result JSON saved from GET /api/status)
python score_chords.py --manifest manifest.json --hyps-dir hyps --tag template
python score_chords.py --ref refs/syn_c_f_g_c.lab --hyp hyps/syn_c_f_g_c.template.json
```

`--run` writes hyps to `hyps/<song_id>.<tag>.json` (gitignored), then scores.
Missing audio or engine failures `SKIP` that song instead of aborting.
