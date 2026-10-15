# Chordex Improvement Plan — lyrics speed, lyrics accuracy, chord↔lyric alignment

Status: **PLAN, awaiting approval.** No code has been changed.
Date: 2026-10-15 · Basis: full read of `backend/`, `frontend/`, `eval/`, real timings from
`.run/logs/worker-lyrics.log`, a read-only probe of the installed venv, and `moises-rea-report.md`.

---

## Phase 1 — Current state of Chordex

### 1.1 Stack and topology

| Layer | What it is |
|---|---|
| Frontend | Next.js 16 / React, TanStack Query polling (`frontend/app/results/[jobId]/page.tsx`), Tailwind. No test runner. |
| API | FastAPI `backend/main.py`: `POST /api/analyze`, `GET /api/status/{id}`, `DELETE /api/jobs/{id}`, `GET /api/audio/{id}` |
| Jobs | Redis + RQ, **async, two queues**: `chord_jobs` → `worker.run_chords`, `lyrics_jobs` → `worker.run_lyrics`. `start.sh` launches one worker process per queue, so chords and lyrics already run in parallel. |
| Result delivery | Chord job writes `result:{id}`, lyrics job writes `lyrics:{id}`. `get_status` merges them. The frontend renders chords first and keeps polling for lyrics. |
| Models | All local. Chordino (Vamp, CPU), Demucs, faster-whisper / transformers, MMS aligner (intended). **Everything is pinned to CPU** (`WHISPER_DEVICE=cpu` in `start.sh`; Demucs hard-codes `device="cpu"` in `pipeline/separation.py:_separate_demucs`). |
| Hardware (dev box) | 12 cores, 13 GB RAM, **NVIDIA GTX 1650 (4 GB)**. `torch 2.14+cu130` reports `cuda=True` and CTranslate2 sees 1 CUDA device. The GPU is idle. |

### 1.2 Upload → display pipeline

1. **Upload**: `main.py:analyze` stores bytes at `UPLOAD_DIR/<job>/audio.<ext>` (`storage.save_upload`). **The original filename is thrown away.** It then enqueues `run_chords` and `run_lyrics` with the optional title, artist and language from the form.
2. **Chords** (`worker.run_chords` → `chord_detector.detect_chords` → `chord_engine/chordino_engine.py`):
   - Vamp/Chordino decodes the file itself (decode #1). `librosa.load(sr=22050)` decodes it again (decode #2).
   - `postprocess.build_result` merges labels, absorbs segments shorter than 0.4 s, runs one `beat_track`, snaps boundaries to beats within 0.35 s, and estimates key with Krumhansl correlation.
   - **The beat times are computed and then discarded.** No beat or bar grid reaches the client.
   - Output: `chords[{timestamp,end,chord,confidence}]`, tempo, key, duration. An `easy` block is precomputed by `easy_chords.apply_easy_mode`.
   - Measured: **8.6 s** for a 5-minute song.
3. **Lyrics** (`worker.run_lyrics` → `lyrics_transcriber.transcribe_lyrics`):
   - **Lookup** (`pipeline/lyrics_lookup.py`): LRCLIB `get` then `search`, using title/artist from the form, then ID3 tags, then the filename. Because of step 1 the filename is always `audio`, so the logs show `lrclib miss title='audio'`.
   - **Separation** (`pipeline/separation.py`): Demucs `htdemucs_ft` on CPU, written as a 16 kHz mono WAV and cached by content hash. `htdemucs_ft` is a bag of four models, so it costs about 4× `htdemucs`. Separation always runs, including after an LRCLIB hit.
   - **ASR** (`pipeline/asr.py`):
     - The model comes from `cfg.asr_model_for(lang_hint)` *before* any language detection. With the default "auto" this always resolves to `small`, so the Indic fine-tunes never run unless the user picks a language.
     - Detection then labelled the Malayalam test song as **Tamil** (`lang=ta`).
     - The vocal stem is cut into 12 s windows with 2 s overlap. An RMS gate drops quiet windows.
     - Each window is written to a temp WAV and passed to `model.transcribe` with its own VAD, beam search of 5 and `word_timestamps`.
     - Overlapping seams are de-duplicated and repeated n-gram loops are dropped.
     - Whisper's encoder always pads input to 30 s, so a 12 s window wastes about 60 % of encoder compute.
     - Hindi and Malayalam fine-tunes (`adalat-ai/*`) would run through the **transformers fp32 pipeline**, not CTranslate2.
   - **Alignment** (`pipeline/alignment.py`): this is meant to be MMS CTC forced alignment, but **it has never run.**
     - `requirements.txt` pins PyPI `ctc-forced-aligner==1.0.2`. That is an unrelated deskpai package: ONNX-based, with a 31-character Latin vocabulary.
     - `from ctc_forced_aligner import load_alignment_model` therefore raises `ImportError`, which the code reports as "not installed".
     - Every job falls back to `words_even_split`. That fallback exists, but on the ASR path the Whisper DTW word times pass through unchanged, and on the LRCLIB path words are spread evenly across each line.
   - **Cleanup** (LLM hook, off by default) and **romanisation**, line-level only, via `indic-transliteration`.
4. **Merge** happens only on the frontend, in `frontend/lib/chordSheet.ts:buildSheet`:
   - **It ignores the backend `lines` whenever words exist.** It regroups words into lines using a 0.55 s pause and 12 words maximum, which duplicates `lyrics_transcriber._lines_from_words`. LRCLIB's real line breaks are lost.
   - For each chord it picks the "first word whose `end` > chord time". That rule picks the word the chord falls *inside*, not the word with the nearest onset.
   - Fixed tolerances: 0.6 s before a line and 0.6 s after the last word. Gaps longer than 8 s get an INTRO or INSTRUMENTAL row.
5. **Rendering** (`frontend/components/ChordSheet.tsx`):
   - Each word is an `inline-flex flex-col` with its chord chips above. Words sit in a `flex-wrap` row, so wrapping keeps chord-to-word association (good). Chips wider than their word push the next word over (acceptable).
   - Gaps: chords have no position *inside* a word, and a chord in a pause between two words has no slot of its own.
   - "Roman" mode loses anchoring entirely: all chips are dumped above the line, and roman lines are matched by timestamp against differently grouped lines.
6. **Easy Mode**: `frontend/lib/easyChords.ts`, which mirrors `backend/easy_chords.py`.
   - It tries capo 0–7, simplifies extensions (maj7→maj, 9→7, and so on), and scores difficulty per shape. It maps 1:1 by index and keeps timestamps, so it is independent of lyrics.
   - The client recomputes everything; the backend `easy` block is only a fallback.
   - Bug: simplifying can make neighbours identical (C → Cmaj7 → C becomes C C C), which shows redundant chips.

### 1.3 Where the time goes (measured, CPU, from `worker-lyrics.log`)

| Stage | Chahun Main Ya Naa (305 s) | Mazha… (296 s) | Scaled to a typical 3.5-min song |
|---|---|---|---|
| Chords (parallel job) | 8.6 s | — | ~6 s |
| LRCLIB lookup | 2.4 s (miss) | 2.9 s (miss, title "audio") | ~3 s |
| **Demucs htdemucs_ft (CPU)** | **551 s** | **576 s** | **~390 s (≈ 83 %)** |
| ASR faster-whisper `small` int8 CPU | 92 s | 108 s | ~70 s (≈ 15 %) |
| Alignment | 0.05 s (broken → even-split) | 0.06 s | — |
| **Lyrics total** | **646 s** | **687 s** | **~7.5 min** |

Chords take seconds. Lyrics take more than 10 minutes, and **separation is about 85 % of it.**

### 1.4 Bugs, dead code, redundancy, fragility

| # | Issue | Where | Impact |
|---|---|---|---|
| B1 | Original filename discarded, so LRCLIB looks up the title "audio" | `storage.save_upload`, `lyrics_lookup.get_metadata` | Verified lyrics are almost never found |
| B2 | Forced alignment never runs (wrong PyPI package; `ImportError` reported as "not installed") | `requirements.txt`, `pipeline/alignment.py` | Word timing is coarse, so chords land on the wrong word |
| B3 | Model routing happens before language detection; "auto" never uses the Indic models; Malayalam detected as Tamil | `pipeline/asr.py:transcribe_asr`, `config.asr_model_for` | Poor accuracy for hi/ml |
| B4 | GPU unused; Demucs device hard-coded | `separation.py`, `start.sh` | 10–30× slower than necessary on this box |
| B5 | `htdemucs_ft` (4-model bag) by default | `config.demucs_model` | About 4× separation cost |
| B6 | 12 s chunks padded to 30 s by Whisper, a temp WAV per chunk, per-chunk VAD | `asr._transcribe_fw` / `_transcribe_hf` | About 2–3× wasted ASR compute |
| B7 | RQ forks a fresh work horse per job, so module-level model caches (`_fw_models`, `_model_cache`) die after every job | `worker.py` (default `Worker`) | Model reload on every job |
| B8 | Vocal stem decoded 3× (`_audible_spans`, `_transcribe_*`, alignment) plus repeated `get_duration`; the original decoded 3–4× across jobs | `asr.py`, `alignment.py`, `chordino_engine.py` | Seconds wasted, messy code |
| B9 | Frontend regroups lines and drops backend/LRCLIB lines; line grouping duplicated in Python and TypeScript | `chordSheet.ts`, `lyrics_transcriber._lines_from_words` | Wrong line breaks; two sources of truth |
| B10 | Chord anchor is "word containing the chord time" rather than nearest onset; fixed 0.6 s tolerances that ignore tempo | `chordSheet.ts:buildSheet` | Chords sit one word early |
| B11 | Beat grid computed then discarded | `postprocess.build_result` | No bar-aware layout, no tempo-relative tolerances |
| B12 | Alignment truncates to `min(roman, native)` tokens when counts differ, silently dropping trailing words | `alignment.align` | Words lost once alignment works |
| B13 | Alignment would run over the whole song in one pass, with no per-line windows | `alignment.align` | Drift into instrumental gaps |
| B14 | Romanisation is line-level only; roman mode loses chord anchoring | `cleanup.romanise_lines`, `ChordSheet.tsx` | Roman view unusable for playing |
| B15 | Easy Mode leaves adjacent duplicate chords after simplification | `easyChords.ts`, `easy_chords.py` | Noisy sheet |
| B16 | Conflicting model tables (`_DEFAULT_MODEL_OVERRIDES`→turbo vs `asr_model_for`→adalat); dead `_separate_vocals`; legacy `_transcribe` duplicates `_transcribe_fw` | `lyrics_transcriber.py` | Confusing; hard to reason about the fallback |
| B17 | Comment says separation is skipped on an LRCLIB hit; the code always separates | `lyrics_transcriber.py` | Misleading |
| B18 | `/api/audio` returns the whole file and ignores `Range` while advertising `Accept-Ranges` | `main.py:get_audio` | Seeking is fragile (especially Safari), which hurts play-along sync |
| B19 | No eval references exist: `eval/refs/*.txt` and `eval/chords/refs/*.lab` are TODO stubs | `eval/` | No accuracy can be measured yet |

Existing tests: `pytest` → 61 passed, 1 skipped. None of them cover chord-to-word placement, which only exists in TypeScript.

---

## Phase 2 — What the Moises report actually tells us

The report reverse-engineers **contracts and observable behaviour**: SDK schemas, HAR payloads and job timestamps. It does **not** show models, server code, or how a chord-over-lyric sheet would be rendered. Moises shows chords and lyrics as separate DAW lanes, not as a lead sheet.

| Topic | What Moises appears to do | Evidence |
|---|---|---|
| Vocal isolation before ASR | `SEPARATE_B` runs in the same task as `LYRICS_B` | **Strong** that separation runs. **Speculative** that ASR consumes the vocal stem. |
| Lyrics + word timing | `LYRICS_B` returns lines → words with a per-word `score` (0–1), and **syllable** timings; params `{alignment: "syllable", language: "auto-detect"}` | **Strong** (schema plus real payload). That a separate forced-alignment pass exists is **moderate**: the `alignment` param suggests it. |
| Language coverage | Malayalam → `FAILED`, English → `COMPLETED` | **Strong.** Malayalam and Hindi, our core languages, are outside its coverage, so it is no benchmark for them. |
| Speed | All operations completed about 25 s after upload for a 183 s song; lyrics took about 20 s | **Strong** (HAR timestamps). That it uses a GPU fleet is **inferred**. |
| Chords + beat grid | `beatMap[{time, beatNum}]` with downbeats; `chords.json` has **one event per beat** with `bar_num` and `beat_num`, so chords are quantised to beats and bars | **Strong** |
| Chord-change → lyric mapping | Not covered; lanes are joined only by time on a timeline | **None.** Our approach has to be designed independently. |
| Data model | Separate time-keyed lists (chordMap, lyrics lines/words, sections), joined on the client | **Strong** for the lists; rendering unknown |
| Sections | `SEGMENTATION_C` → Intro/Verse/Chorus/Instrumental Solo spans | **Strong** |
| Simplified chords | Every chord ships at 3 levels (`complex/simple/basic`) × 3 notations; fret diagrams fetched with `difficulty: EASY` | **Strong.** Capo or transposition logic is **not covered**. |
| Performance tricks | Independent per-operation jobs run in parallel, each with its own status (progressive per lane), `onUpdate` progress, `watch` to resume | **Strong** for parallel ops and progress. **No evidence** about caching. |
| Tuning | `detuningCents`, `estimatedTuning` | **Strong** (minor for us) |

**Corrections and cautions about the report:**
1. It says nothing about how chord-over-lyric display works. All display and alignment work here is our own design.
2. Its speed figures reflect server GPUs. Our target depends on deployment hardware (see open question Q1).
3. Do not use the Moises `chords.json`, `lyrics.json` or SVGs in `/tmp/opencode/` as eval references or assets. They are proprietary output, not ground truth.
4. The "per-beat chord events" idea maps cleanly onto our beat-snap stage. The "syllable alignment" idea maps onto character-level CTC alignment, which our MMS path can produce.

---

## Phase 3 — Gap analysis

| Feature | Chordex now | Moises (apparent) | Gap | Proposed change |
|---|---|---|---|---|
| Vocal separation | htdemucs_ft, CPU, about 9.5 min | Separation op, seconds | 20–40× slower | **S1** htdemucs + GPU when available, CPU fallback |
| Verified lyrics | LRCLIB, but the title is always "audio" | n/a (pure ASR) | Hits almost never happen | **S2** keep the upload filename and feed metadata |
| ASR engine | 12 s chunks, per-chunk files, `small` | Fast, auto-detect | Wasted compute; wrong model | **S3** batched whole-file faster-whisper with VAD; **A1** detect then route; **A2** Indic fine-tunes as CT2 int8 |
| Language | auto → `small`; ml→"ta" | Auto-detect; explicit failure when unsupported | Wrong language and model | **A1** stem-based multi-window detection; "unsupported language" state |
| Word timing | Whisper DTW or even-split (aligner broken) | Word + syllable timing with scores | Coarse and occasionally wildly off | **A3** torchaudio MMS_FA forced alignment per line window; char-level times and confidence |
| Beat grid | Computed, discarded | beatMap with downbeats | Missing | **L1** return beats and tempo; tempo-relative tolerances; bar rows for instrumentals |
| Chord → word | "Word containing t" in the frontend, fixed 0.6 s | n/a | Chords one word early; no mid-word or gap slots | **L2** backend `sheet` builder with nearest-onset rule, mid-word and gap slots, lead-ins; pytest suite |
| Data model | Two parallel arrays; merge in TypeScript | Separate time-keyed lanes | No single tested intermediate | **L2** ChordPro-like `sheet` JSON (lines → segments) built in Python |
| Lines/sections | Pause regroup in TypeScript; INTRO/INSTRUMENTAL by gaps over 8 s | Section op | LRCLIB lines lost; no chorus labels | **L3** authoritative lines (LRCLIB > ASR segments + pause/beat rule); repeated-line chorus detection |
| Display | Word-anchored chips; no mid-word; roman loses anchors | Lanes | Mid-word and roman broken | **D1** render `sheet` segments as atomic inline anchors; word-level roman; active word highlight |
| Easy Mode | Index-mapped, client recompute | 3 precomputed levels | Duplicate chips | **E1** keep index mapping; suppress repeated labels at render; tests that anchors survive Easy Mode and transpose |
| Progressive | Chords first, lyrics all at once | Per-op status | Fine once lyrics are under 1 min | **S5** (P2) stream partial lyric lines |
| Model lifetime | Forked horse per job | n/a | Reloads | **S4** `SimpleWorker` for the lyrics queue |

### Prioritised improvements (impact ÷ effort/risk)

| Pri | ID | Change | Area | Impact | Effort | Risk |
|---|---|---|---|---|---|---|
| P0 | M0 | Baseline harness: per-stage timing JSON, `eval/run_eval.py`, placement metric | Eval | Enables everything | S | Low |
| P0 | S1 | Demucs `htdemucs` + `device=auto` (CUDA if present) | Speed | ~390 s → ~100 s CPU / ~15 s GPU (est.) | S | Low |
| P0 | S2 | Persist the original filename; use it in metadata | Accuracy + speed | LRCLIB hits skip ASR | S | Low |
| P0 | A3 | Replace the broken aligner with torchaudio `MMS_FA` + `forced_align`, per-line windows, char times | Alignment | Word onsets ±50–100 ms (est.) instead of ±0.3–1 s | M | Med |
| P0 | L2 | Backend `sheet` builder (ChordPro-like) + nearest-onset anchoring + pytest | Alignment | Core fix for "when to switch" | M | Med |
| P0 | S3 | Whole-file `BatchedInferencePipeline` + Silero VAD on the stem; no temp chunks | Speed | ~70 s → ~20–25 s CPU / ~5 s GPU (est.) | M | Low |
| P0 | A1 | Detect language on the stem, *then* route the model | Accuracy | Indic models actually used | S | Low |
| P1 | D1 | Render `sheet` segments as inline anchors; mid-word; word-level roman | Display | Readable, wrap-safe | M | Low |
| P1 | L1 | Return beats/tempo; tempo-relative tolerances; bar rows in instrumentals | Alignment | Better snap and gap layout | S | Low |
| P1 | A2 | Convert `adalat-ai` hi/ml medium to CT2 int8; drop the transformers fp32 path from the default | Accuracy + speed | Indic quality without fp32 cost | M | Med |
| P1 | S4 | `SimpleWorker` for `lyrics_jobs` (models stay loaded) | Speed | −5–20 s per job (est.) | S | Low |
| P1 | E1 | Easy Mode duplicate suppression + regression tests | Easy | Clean sheet | S | Low |
| P1 | L3 | Authoritative lines + chorus detection from repeated lines | Display | Sections like a real sheet | S | Low |
| P2 | S5 | Stream partial lyric lines to the UI | Speed (perceived) | Nice to have once total is under 1 min | M | Med |
| P2 | A4 | User lyric edit + re-align-only job | Accuracy | Escape hatch for bad ASR | M | Low |
| P2 | X1 | Audio `Range` support (B18); remove dead code and duplicate tables (B16/B17) | Robustness | Seeking works everywhere | S | Low |

---

## Change details

Each change states the files affected, dependencies, risks, and verification. "est." means a projection; Phase 4 will measure the real number.

### M0 — Baseline and measurement harness
- **Files**: `lyrics_transcriber.py` (already returns `stages`; add `decode`/`vad` stages), `worker.py` (persist `stages` and `chords_stages` in the result), new `eval/run_eval.py` (runs the full pipeline offline on each manifest song with no Redis and writes `eval/runs/<tag>.json`), and `eval/score.py` (reuses the existing CER/WER).
- **New metric, `eval/score_placement.py`**:
  - Reference format: ChordPro text, e.g. `[G]Wise men [D]say`.
  - Our `sheet` and the reference are aligned word-to-word by Levenshtein on normalised tokens, so ASR errors don't cascade.
  - **Placement accuracy** = share of reference chord markers whose aligned word (± same syllable when marked mid-word) carries the same chord change in our sheet.
  - Also reported: **chord-onset error** in ms against the `.lab` reference, and **word-onset MAE** on hand-labelled words.
- **Deps**: none.
- **Verify**: run on the 2 test songs and record the baseline row before any other change.

### S1 — Faster separation
- **Files**:
  - `pipeline/separation.py`: `device` from a new `cfg.separation_device` (`auto` → cuda if `torch.cuda.is_available()`).
  - The default model becomes `htdemucs`, with `htdemucs_ft` kept as an opt-in "quality" setting.
  - Use `segment` and `split=True` so 4 GB VRAM is enough; fall back to CPU on CUDA OOM.
  - Also touched: `pipeline/config.py`, `start.sh` (`LYRICS_DEVICE=auto`), `.env.example`.
- **Deps**: none (torch cu130 is already installed). **GPU**: htdemucs needs about 1.5–2.5 GB VRAM with segmenting.
- **Risks**: `htdemucs` vocal quality is slightly lower than `_ft`, so check that CER doesn't regress. The GPU is shared with the desktop.
- **Verify**: separation seconds before and after on both songs; CER delta on the eval set; listen to the stems.

### S2 — Keep upload metadata
- **Files**: `main.py` (pass `file.filename` into the lyrics job kwargs), `worker.run_lyrics`, `lyrics_transcriber.transcribe_lyrics`, and `lyrics_lookup.get_metadata` (accept `filename_hint` and parse it instead of `audio.mp3`). The cache key gains the filename-derived title.
- **Deps**: none. **Risk**: wrong-song hits. The existing duration ±3 s and fuzzy title/artist guards stay.
- **Verify**: unit test showing that "Chahun Main Ya Naa Aashiqui 2 320 Kbps.mp3" parses to a sane title; a live LRCLIB check on the test songs; log the `lyrics_source`.

### S3 — ASR without the chunk tax
- **Files**: `pipeline/asr.py`.
  - Replace `_transcribe_fw`'s manual 12 s loop with one `BatchedInferencePipeline(model).transcribe(audio_array, batch_size=8, vad_filter=True, word_timestamps=True, language=…)` on the 16 kHz stem array that is already in memory.
  - Keep `_drop_repeat_loops`, add the `no_speech`/`compression_ratio` guards, and delete `_audible_spans` (VAD replaces the RMS gate).
  - Pass the decoded array (decode once, B8).
- **Deps**: none (`faster-whisper 1.2.1` ships `BatchedInferencePipeline` and Silero VAD).
- **Risks**:
  - Batched mode slightly changes segmentation.
  - CTranslate2 4.x on CUDA needs the CUDA 12 cuBLAS/cuDNN 9 libraries, but the venv has CUDA 13 wheels from torch. Phase 4 will verify; if it fails, ASR stays on CPU int8 while Demucs and the aligner use the GPU.
- **Verify**: ASR seconds and WER/CER before and after on the eval set.

### A1 — Detect, then route
- **Files**: `pipeline/asr.py`.
  - If there's no hint, run `model.detect_language` on 3–5 VAD-voiced 30 s windows of the stem and take a probability-weighted vote.
  - Then call `cfg.asr_model_for(detected)`. Optionally restrict candidates (`LYRICS_LANG_CANDIDATES=en,hi,ml,ta`) to stop ml→ta.
  - Expose `lyrics_language_confidence` and an "unsupported/uncertain language" status to the UI (idea from the Moises report).
- **Verify**: language correct on all eval songs with "auto".

### A2 — Indic fine-tunes on CTranslate2
- **Files**: new `backend/scripts/convert_ct2.py` (wraps `ct2-transformers-converter --quantization int8`), `config.asr_model_for` (point to local CT2 dirs when present), `prewarm.py`.
  - Delete the conflicting `_DEFAULT_MODEL_OVERRIDES` table and the legacy `_transcribe` path in `lyrics_transcriber.py`; the single fallback becomes `large-v3-turbo` (B16).
- **Deps**: none new; weights about 0.8 GB per model in int8, Apache-2.0.
- **Risk**: conversion quirks with fine-tuned tokenizers; validate CER against the transformers version on one song.
- **Verify**: CER/WER for adalat CT2 vs `small` vs `large-v3-turbo` on the hi and ml songs; the table goes into `eval/results.md`.

### A3 — Forced alignment that actually works
- **Files**:
  - `pipeline/alignment.py` is rewritten around `torchaudio.pipelines.MMS_FA` (emission model) and `torchaudio.functional.forced_align`. Romanisation uses the already-installed `uroman`.
  - **Per-line windows**: each line is aligned inside `[line.start − 0.5 s, line.end + 0.5 s]`, using Whisper segment bounds or LRCLIB line stamps. That prevents drift into instrumentals (B13). Unsynced LRCLIB text goes through a coarse whole-song pass first, then per-line refinement.
  - Keep a **native ↔ roman word index map** instead of truncating (B12).
  - Emit per-word `confidence` and per-word `chars: [{t}]` onset times. These give the "syllable-level" capability: they let a chord land mid-word.
  - Low-confidence words fall back to the Whisper times.
  - Remove `ctc-forced-aligner==1.0.2` from `requirements.txt` and fix the `LICENSE-NOTES.md` entry.
- **Deps**: torchaudio (installed). MMS_FA weights are about 1.2 GB, **CC-BY-NC-4.0**, which LICENSE-NOTES already accepts for personal use. `forced_align` is flagged for deprecation in recent torchaudio, so we pin the current version and include a small in-house NumPy CTC Viterbi fallback (≈60 lines, unit-tested) so a future torchaudio removal doesn't break us.
- **GPU**: about 1.3 GB fp16; works on CPU at roughly 0.2× realtime.
- **Verify**: word-onset MAE on hand-labelled words (target under 100 ms) and the share of low-confidence words. A test on a synthetic TTS/fixture clip checks monotonic, in-window timestamps.

### L1 — Beat grid out of the chord job
- **Files**: `postprocess.build_result` (return `beats` and `tempo`), `chordino_engine.py`, `api.ts` types.
  - Optional downbeat estimate: the highest-energy phase out of 4 beats; label it a heuristic.
- **Deps**: none. A real downbeat model (`beat_this`, MIT, ~80 MB torch) is a later option, not part of this plan.
- **Verify**: beat count vs `librosa` tempo sanity check; used by L2 tolerances.

### L2 — Backend `sheet` builder (the core alignment fix)
- **New** `backend/pipeline/sheet.py`. It is pure, deterministic and has no I/O. It is called from `main.get_status` when both chords and lyrics exist, and the result is cached as `sheet:{id}`. That avoids the race over which job finishes first.
- **Data model** (ChordPro-like). Chords are referenced by **index**, so transpose and Easy Mode keep working purely on the client:
  ```json
  {"version":1,
   "rows":[
    {"kind":"section","label":"INTRO","t":0.0},
    {"kind":"bars","t":0.0,"bars":[[0],[1],[2,3]]},
    {"kind":"line","t":12.4,"end":15.9,"carry":2,
     "words":[{"text":"Wise","t":12.4,"end":12.8,
               "segs":[{"chord":3,"text":"Wise"}]},
              {"text":"beautiful","t":13.1,"end":13.9,
               "segs":[{"chord":null,"text":"beau"},{"chord":4,"text":"tiful"}]}],
     "gaps":[{"after_word":1,"chord":5}]}]}
  ```
- **Anchoring rules**, with tolerances scaled to the beat period `B` (default 0.5 s when tempo is unknown):
  1. A chord change at time `t` goes to the word whose **onset is nearest** within `[−0.5B, +0.5B]`. Ties go to the later word, because singers often anticipate the beat.
  2. If no onset is that close and `t` falls inside a word lasting at least 0.35 s, the chord goes **mid-word** at the nearest character onset (from A3 `chars`). Without char times, split proportionally at a vowel/syllable boundary.
  3. If `t` falls in a pause between words in the same line, it becomes a **gap slot** rendered between them.
  4. Chords between lines: within 1 bar before the next line, they become a lead-in on its first word. Otherwise they become an instrumental `bars` row grouped by beat count. Gaps of at least 2 bars get a `section` row (INTRO/INSTRUMENTAL/OUTRO).
  5. `carry` marks the chord already sounding when a line starts, so users know what to hold.
  6. `N` (no-chord) is never anchored.
- **Lines** (L3): use LRCLIB lines when present. Otherwise use Whisper segments split on pauses of at least `max(0.55 s, 1B)` and about 42 characters maximum. The TypeScript regrouping is deleted (B9).
- **Tests** (`backend/tests/test_sheet.py`), table-driven:
  - exact onset
  - anticipation within ±0.5B
  - mid-word, with and without char times
  - gap slot
  - lead-in vs instrumental row
  - chord before the first lyric
  - chord after the last lyric
  - two changes on one word
  - consecutive identical chords
  - empty lyrics (chords-only sheet)
  - untimed lines
  - tempo unknown
  - Easy Mode / transpose index invariance (see E1)
  - property test: every non-N chord appears exactly once in the sheet, in time order
- **Verify**: pytest, plus placement accuracy from M0 on the eval set.

### D1 — Display
- **Files**: `ChordSheet.tsx` renders `sheet` rows; `chordSheet.ts` shrinks to `activeRowIndex` and active-word helpers.
  - Each **word is one `inline-flex` nowrap unit** made of segment columns: chord above, text below. Wrapping can only happen *between* words, so alignment survives any width.
  - Chord wider than its text: the segment gets `min-width` equal to the chord width plus a gap. For mid-word splits, a hyphen-extender (`beau–tiful`) shows the break.
  - Gap slots render as a chord over a narrow spacer.
  - `carry` renders as a faint chord at line start.
  - `bars` rows render as `| G . . . | D . . . |`.
  - Word-level romanisation (`romanise_line` per word, cheap) reuses the same anchors (B14).
  - Active-word highlight from word times; the existing scroll-to-active-row stays.
- **Deps**: none.
- **Verify**: manual check at 360 px, 768 px and 1440 px; an `e2e` smoke test (the global CLI per AGENTS.md) that loads a fixture result and asserts the chord DOM node sits above the expected word.

### E1 — Easy Mode compatibility
- `sheet` uses chord indices and Easy Mode maps 1:1 by index, so it works unchanged. Add:
  - render-time suppression of a chord whose displayed label equals the previous displayed chord within the same line
  - pytest coverage for `easy_chords.apply_easy_mode` index and length preservation
  - a shared JSON fixture asserting the Python and TypeScript `simplify_chord` agree on about 60 labels (kept as a Python test reading a fixture the TypeScript side also uses; no new frontend test runner)
- **Verify**: tests; manual capo/transpose toggling on the eval songs.

### S4 — Keep models loaded
- `worker.py`: use `SimpleWorker` for `lyrics_jobs`. Same process, models stay in module caches, and RQ's death-penalty timeout still applies. Keep the forking `Worker` for chords (the Vamp plugin is the stuck-job risk there).
- **Risk**: memory growth; log RSS per job.
- **Verify**: second-job lyrics time vs first.

### S5 (P2) — Streaming lyrics
- Publish partial lines to `lyrics_partial:{id}` after each ASR batch. `get_status` returns them with `lyrics_status=processing`. The UI renders them greyed out, without chords, until the final `sheet` arrives.

### A4 / X1 (P2)
- **A4**: an editable lyric-line panel, plus `POST /api/jobs/{id}/realign` that runs only A3 and L2 on the cached stem.
- **X1**: `Range` responses in `/api/audio` (`FileResponse` handles ranges for local files); delete the dead `_separate_vocals` and the duplicated model table.

### Expected end state (est., verify in Phase 4)

| Stage (3.5-min song) | Now (CPU) | After, CPU only | After, GTX 1650 |
|---|---|---|---|
| Separation | ~390 s | ~100 s | ~15 s |
| ASR | ~70 s | ~25 s | ~6–10 s |
| Alignment | broken | ~30 s | ~4 s |
| Lyrics total | ~7.5 min | ~2.5 min | ~30 s |
| LRCLIB hit | same as miss | separation + alignment only | ~20 s |

---

## Evaluation approach

**Test set (3–5 songs)**: the two songs in `test-assets/songs/` (Hindi, Malayalam) plus 1–3 more. I recommend one English song as a control: LRCLIB hit likely, Moises comparable. A sparse acoustic track and a dense one would also help.

**Metrics per run** (one row in `eval/results.md`, never averaged across languages):
- total lyrics wall time, chord wall time, per-stage seconds (`stages`)
- lyrics **CER** (primary for ml) and **WER** (existing `eval/score.py` normaliser)
- **word-onset MAE** (ms) on hand-labelled words
- **chord placement accuracy** (% of reference chord markers on the correct word or syllable)
- chord-onset error vs `.lab`, and the existing mir_eval `majmin` score as a regression guard

**What I need from you, per song:**
1. **Audio** you own, dropped into `eval/songs/`.
2. **Reference lyrics**: native script, one sung line per line, in `eval/refs/<id>.txt`. I can pre-fill a draft from LRCLIB for you to correct by ear.
3. **Reference chord sheet in ChordPro**, with the chord placed on the exact syllable where it changes, e.g. `[Am]Chahun main [F]ya [G]naa`, at least 2 verses and 1 chorus. This directly drives the placement metric.
4. *(Optional but valuable)* **~20 word onsets** per song as Audacity label tracks (`start<TAB>end<TAB>word`), which gives word-timing MAE.
5. *(Optional)* fill the existing `.lab` chord-timing stubs (`eval/chords/ANNOTATING.md`).

Until items 2–3 exist, Phase 4 can still measure **all timing numbers** and run the unit tests. CER and placement accuracy will be reported as "not measurable yet", not guessed.

---

## Phase 4 execution order (after approval)
Branch `improve/lyrics-alignment`, one commit per item:
M0 baseline → S2 → S1 → S3 → A1 → A3 → L1 → L2 (+tests) → D1 → E1 → S4 → A2 → L3 → (P2 items if time allows).
Re-measure after S1, S3, A3 and L2/D1, and report before/after numbers for each.

## Open questions
- **Q1 Deployment hardware**: will production have a GPU? The plan defaults to `device=auto`; on CPU-only hosts, lyrics land around 2.5 min instead of about 30 s.
- **Q2 Languages**: are hi/ml the priority, with English as secondary? This decides how much effort goes into A2.
- **Q3 Licensing**: still personal use only? MMS_FA weights are CC-BY-NC.
- **Q4 Merge location**: I recommend the backend `sheet` (testable in pytest, single source). The alternative is keeping it in TypeScript and adding vitest.

---

## Phase 4 — Results (2026-10-15, branch `improve/lyrics-alignment`)

Measured with `eval/run_eval.py` (cold cache, real upload flow without Redis). Raw rows are in `eval/timing.md`.
Baseline = `main@7b8e2e5` on CPU, which is how it shipped. "After" = branch HEAD on the GTX 1650, auto language, routed models.

| Song (length) | Lyrics before | Lyrics after (full ASR path) | After, LRCLIB hit | Language before → after |
|---|---|---|---|---|
| Hindi, Chahun Main Ya Naa (5:05) | 694.7 s | 81.5 s | 46.3 s (live upload: 37.4 s) | en ✗ → hi ✓ |
| Malayalam, Mazha… (4:56) | 612.0 s | 68.2 s | n/a (not on LRCLIB) | ta ✗ → ml ✓ |
| English, Elvis (3:03) | 364.5 s | 27.5 s | (LRCLIB rate-limited during tests) | en → en |

Stage breakdown, Hindi, before → after: separation 607 → 26 s · ASR 86 → 37 s (the medium fine-tune; `small` is 18 s) · alignment 0 s (it never ran) → 19 s. Chords are unchanged at ~7 s.

Corrections to the plan, found while measuring:
- PyPI `ctc-forced-aligner==1.0.2` is an unrelated package. It was replaced with torchaudio MMS_FA plus an in-house CTC Viterbi.
- **Silero VAD drops sustained singing.** It marked 41 of 183 s as voiced on the ballad, which halved the lyrics. An energy gate on the vocal stem replaced it.
- On a GTX 1650, fp16 is 3–4× *slower* than fp32 or int8 (no tensor cores). The aligner runs fp32; Whisper runs int8_float16.
- CTranslate2 needs CUDA 12 cuBLAS while torch ships CUDA 13, so `nvidia-cublas-cu12` is preloaded in-process.
- A long-lived worker on a 4 GB card needs explicit VRAM management (the second song in a new language ran out of memory). It is in place: verified hi → ml → en in one process, peak 3.3 GB.

Not measurable yet: CER/WER, chord-placement accuracy and word-onset error, because no reference files exist (see `eval/refs/REFERENCES.md`). Malayalam/Hindi quality was only checked by eye: the fine-tunes produce recognisable native-script lyrics, where Whisper `small` produced mixed-script garbage.
