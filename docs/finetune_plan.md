# Phase 6 — Singing-adapted fine-tuning plan (design only, DO NOT TRAIN)

No Hindi/Malayalam singing-adapted ASR model is published (only Vietnamese
and Greek equivalents exist). That gap is the opportunity — and why this is
the last phase, after data + eval exist.

## 1. Data (`eval/collect_pairs.py`)

LRCLIB synced lyrics → vocal separation → LRC-line segments → filter
(2–15 s, RMS ≥ −35 dB, align confidence ≥ 0.4) → `(audio, text)` pairs +
`manifest.jsonl`. Target: **50–100 h per language** (Vividh tiers suggest
spontaneous/broadcast tiers matter most for singing robustness). Stratify by
era/production/vocal/reverb tiers from `eval/manifest.json` — never one
aggregate pool.

## 2. Recipe (from the Vividh-ASR ablations — starting point, then verify)

- **High LR 2e-4 is non-negotiable.** Conservative LR traps the model in the
  pretrained basin; low-LR runs roughly doubled WER.
- **No easy→hard curriculum** — it regressed vs single-stage in both languages.
- If a curriculum: **reverse (hard→easy)** (best Malayalam); for Hindi, plain
  single-stage high-LR won outright.
- **Benchmark across acoustic tiers, not one number** — global averages hide
  regressions on the hard conditions that matter in deployment.
- AdamW (weight decay 0.1), ~10% linear warmup, cosine anneal to zero.
- Start from `adalat-ai/whisper-medium-{ml,hi}-*` (Apache-2.0), not base Whisper.
- Validate CTranslate2-int8 quantised artifact on `eval/` before shipping.

## 3. Cost estimate (order-of-magnitude)

- Data: ~2–4 weeks semi-automatic collection + ear-verification per language.
- Compute: medium-Whisper fine-tune ≈ 1–3 days on 4×H100 per language/recipe;
  budget **3–5 recipes × 2 languages ≈ 4–8 weeks GPU-time**.
- Expected gain: 10–25% relative CER on sung eval tiers (speech-adjacent
  tiers less); singing remains harder than any Vividh tier — measure, don't assume.

## 4. Licensing

Commercial song audio cannot be redistributed: ship `collect_pairs.py` +
song-link lists, never waveforms. Model release inherits Whisper Apache-2.0
lineage + training-data constraints — record in LICENSE-NOTES.md.
