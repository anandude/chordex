# A1.0 — Deep chord model: budget & options decision memo

Date: 2026-10-02. Status: **decision needed before any A1.1 code**.
Owner decision: hosting budget (RAM) + which spike to fund first.

## Correction to the earlier estimate

The original plan claimed "+5–15pp vs template-HMM" for a deep model. A
reproducible third-party benchmark (marcusfkelley/btc-hcqt, held-out
GuitarSet/Schubert, mir_eval) finds the open field **plateaued**: BTC, CREMA
and Chordino all land ~73–81% root — gaps within 95% confidence intervals.
Honest expectation for Chordex:

| Swap | Expected deltas on OUR harness (A3) |
|---|---|
| template-HMM → deep model | +3–8pp majmin (real, worth it) |
| Chordino → deep model | **+0–5pp**, mostly on 7ths/inversions (marginal — measure, don't assume) |

The deep model is still the highest-accuracy option, but it is an
increment over Chordino, not a revolution. The cheap wins (A2 key-aware
Viterbi, calibration) may capture half the gap for ~0 RAM.

## Options (verified 2026-10-02)

| | BTC (Park et al., ISMIR19) | BTC+HCQT parity weights | CREMA (McFee/Bello) |
|---|---|---|---|
| Code | jayg996/BTC-ISMIR19, **MIT**, PyTorch | marcusfkelley/btc-hcqt, **MIT** | `pip install crema`, docs + JAMS output |
| Weights | **NOT published** — train yourself (needs copyrighted audio) or hunt forks | **`btc_hcqt_beatlesft.pt` ships in repo**, needs BTC's `btc_model.py` body | ships via package (verify size on install) |
| Vocab | maj/min (+large-vocab flag) | same as BTC | **602 classes** incl. inversions |
| Extra deps | torch (already in env for demucs) + pyrubberband + pretty_midi | same + HCQT precompute | **verify: TF vs torch**, jams, mir_eval |
| CPU cost | transformer, full-song CQT frontend — slower than Chordino, measure | same | CNN structured prediction — measure |
| Integration | new `btc_engine.py` behind `CHORD_ENGINE=btc`, weight cache via existing `hf_cache` pattern (or vendored `.pt`) | same body, different checkpoint | new `crema_engine.py`, JAMS→Harte mapping |

## Costs to confirm before A1.1 (5-minute checks on a dev machine)

1. `pip install crema` → weights size on disk? TF dependency or torch?
2. `btc_hcqt_beatlesft.pt` download size? (repo file — check before vendoring)
3. Peak RSS running each over `test-assets/songs/*.mp3` on CPU vs current
   engines (our Render free tier is 512 MB — whisper+demucs already fight it).
4. Wall time per song per engine (feeds the S3 UX story: deep model only
   makes sense on the chord job if it stays under ~60 s).

## Recommended spike order (pending your call)

1. **CREMA first** — one `pip install`, JAMS output maps cleanly to Harte,
   biggest vocab (inversions help guitarists). Keep iff A3 harness shows
   +pp majmin AND +pp sevenths vs Chordino on our songs.
2. **BTC second** — best pedigree; use the btc-hcqt parity weights to skip
   training. Keep iff it beats the CREMA spike.
3. Loser is deleted, winner gets `CHORD_ENGINE` flag + Docker weight caching
   + a `results.md` row. No two-deep-model maintenance.

## Your decisions (recorded 2026-10-02)

- [x] Hosting: **stay on free 512 MB** — A1 deep models parked until/unless
      A2/A4 results show the gap is worth paid RAM. Consequence: any future
      spike must fit demucs + whisper + model in 512 MB or shed load
      (e.g. smaller whisper, lyrics off for the comparison run).
- [x] Spike order: **CREMA first**, BTC second — when unblocked.
- [x] Weights: **vendored in repo** if a model wins — NOTE tension with the
      free-tier call: vendored weights + 512 MB + demucs/whisper is the
      highest OOM risk combo. Revisit (download-on-first-run or Starter)
      if the spike ever justifies it.
