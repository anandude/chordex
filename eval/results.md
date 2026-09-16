# Lyrics eval results (append-only)

One row per config. CER is primary (esp. Malayalam); WER secondary. Hindi and Malayalam are never averaged. Normalizer: NFC, strip punctuation, collapse whitespace, lowercase Latin only (see `eval/score.py::normalize`).

| date | config | n_hi | hi_CER | hi_WER | n_ml | ml_CER | ml_WER | sec/song | notes |
|---|---|---|---|---|---|---|---|---|---|
| 2026-09-13 | baseline | 0 | - | - | 0 | - | - | - | harness validated; 0/12 songs scored — audio + hand-verified refs pending from owner (see manifest.json) |
| 2026-09-13 | sep-demucs-htdemucs | 0 | - | - | 0 | - | - | 12.4 | Phase 1 module e2e on 8 s fixture: 16 kHz mono stem, 12.4 s cold / 0.00 s cache-hit; htdemucs_ft pinned (dl on first use). CER pending songs |
| 2026-09-13 | sep-roformer | 0 | - | - | 0 | - | - | - | audio-separator 0.47.0 API verified from sdist; pkg absent here → mixture fallback verified. SHIP DEMUCS for now (reliable default); benchmark roformer (`mel_band_roformer_vocals_becruily.ckpt`) once songs land |
| 2026-09-13 | lrclib | 0 | - | - | 0 | - | - | - | live /api/search verified; miss→ASR fallback verified; title/artist UI fields added. Hit-rate + wrong-song QA pending songs |
| 2026-09-13 | asr-indic-routing | 0 | - | - | 0 | - | - | - | routing (ml→medium-ml-rmft, hi→medium-hi-high-lr, 12 s+2 s chunks, RMS gate, seam dedup) unit-tested; HF IDs verified Apache-2.0; legacy turbo fallback intact. Per-model CER rows pending songs + weights |
| 2026-09-13 | align-ctc | 0 | - | - | 0 | - | - | - | ctc-forced-aligner 1.0.2 API verified (ISO-639-3, romanize); even-split fallback + chord-timebase test pass. Onset-error study pending songs. NOTE MMS weights CC-BY-NC — commercial blocker, see LICENSE-NOTES.md |
| 2026-09-13 | cleanup-roman | 0 | - | - | 0 | - | - | - | LLM hook no-op + raw-kept-for-diff tested; IndicXlit API verified from installed pkg (src_script_type=indic); native/roman/both toggle in UI. CER delta pending songs — ship OFF for cleanup, ON for toggle |
| 2026-09-13 | lrclib-live | 0 | - | - | 0 | - | - | 1.6 | Kesariya/Arijit stand-in (duration-matched): exact hit → lrclib_synced, 39 lines / 263 words native Hindi. Lookup chain proven; hit-rate pending real uploads |
| 2026-09-13 | roman-indic-live | 0 | - | - | 0 | - | - | - | REPORT: IndicXlit unrunnable (fairseq broken on py3.11, no GoVarnam py pkg). Shipped `indic-transliteration` sanscript backend instead (pure Python, verified: ഹലോ ലോകം→halo lokaM). Xlit path kept behind LYRICS_ROMAN_BACKEND=xlit |
| 2026-09-14 | services-rerun | 0 | - | - | 0 | - | - | 28.0 | all services restarted; fixture e2e done C-F-G-C via demucs+turbo fallback; 38/38 pytest + tsc clean. HF weights still downloading (targeted fetch: root model.safetensors only, checkpoint-* dirs identified as 5 GB waste) |
