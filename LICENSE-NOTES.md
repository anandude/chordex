# License notes — lyrics pipeline models & data

Every weight/API below was verified against its actual source (model card,
PyPI, live API) before wiring. Verify again before changing pins.

| Component | Artifact | License | Commercial? |
|---|---|---|---|
| Demucs (`demucs`, incl. `htdemucs_ft`) | weights + code | MIT | ✅ |
| audio-separator (`==0.47.0`) + RoFormer vocals ckpts (e.g. `mel_band_roformer_vocals_becruily.ckpt`) | code MIT; community checkpoints vary | MIT (code); checkpoint cards must be checked per file | ⚠️ check checkpoint card |
| faster-whisper / CTranslate2 runtime | code | MIT | ✅ |
| OpenAI Whisper stock ids (`small`, `large-v3-turbo`) | weights | Apache-2.0 lineage | ✅ |
| `adalat-ai/whisper-medium-ml-rmft`, `whisper-medium-hi-high-lr`, `whisper-small-ml-rmft`, `whisper-small-hi-high-lr` | weights | Apache-2.0 (model cards) | ✅ |
| `thennal/whisper-medium-ml` | weights | Apache-2.0 | ✅ |
| `vasista22/whisper-hindi-large-v2` | weights | Apache-2.0 | ✅ |
| `Sanat-agrwl/indic-crisperwhisper-hindi-v1` (brief said `user71/…` — stale, corrected) | weights + custom retok code | MIT | ✅ (custom code path) |
| `ai4bharat/indic-conformer-600m-multilingual` | weights + `trust_remote_code` | MIT, **gated** (accept conditions + `HF_TOKEN`) | ✅ after gating |
| `ctc-forced-aligner` package | code | BSD-2-Clause | ✅ |
| MMS forced-aligner weights (`MahmoudAshraf/mms-300m-1130-forced-aligner`) | weights | **CC-BY-NC-4.0 (non-commercial)** | ❌ **BLOCKER for commercial use** — `pipeline/alignment.py::ALIGN_FN` is swappable; investigate an Apache/MIT alternative before this becomes load-bearing |
| IndicXlit (`ai4bharat-transliteration==1.1.3`) | code + 11M-param model | MIT | ⚠️ wired but unrunnable here (needs fairseq/broken on py3.11); default roman backend is `indic-transliteration==2.3.82` (MIT, pure Python) |
| LRCLIB (`https://lrclib.net`) | API + user-contributed lyrics | free, no key; contents user-contributed, **not licensed** | ⚠️ personal use ok; get clarity before scaling |

**Copyright note (not a coding task):** song lyrics are copyrighted. LRCLIB
contents are user contributions, not licensed masters. Fine for personal use;
get legal clarity before scaling beyond it. Training data (Phase 6) must be
reproducible from links, never redistributed as audio.

**Project status (owner-confirmed 2026-09-13): personal use only.** The MMS
CC-BY-NC aligner weights are therefore acceptable as-is. If this ever moves
toward commercial use, revisit the alignment backend FIRST (swappable via
`pipeline/alignment.py::ALIGN_FN`) and re-clear LRCLIB-sourced lyrics.
