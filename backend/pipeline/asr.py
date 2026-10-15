"""
pipeline/asr.py
---------------
Phase 3 — language-specific ASR over the isolated vocal stem.

Flow (``transcribe_asr``):
  1. Decode the 16 kHz mono stem ONCE into memory; every step reuses the array.
  2. A1 — language ID *before* routing: with no per-job hint, a stock Whisper
     model (``LYRICS_LID_MODEL``) votes over the first voiced windows, biased
     toward ``LYRICS_LANG_CANDIDATES`` (singing confuses ml↔ta). Routing then
     picks the language's model — previously "auto" always meant ``small``
     and the Indic fine-tunes never ran.
  3. S3 — one batched pass: faster-whisper's ``BatchedInferencePipeline``
     decodes ≤20–30 s
     batches over energy-gated voiced windows of the stem (NOT Silero VAD,
     which misses sustained singing). The old path cut 12 s windows into temp WAVs; Whisper's
     encoder pads every input to 30 s, so ~60 % of encoder work was padding.

Routing (``LyricsConfig.asr_model_for``):
  ml → adalat-ai/whisper-medium-ml-rmft (769M, Apache-2.0)
  hi → adalat-ai/whisper-medium-hi-high-lr (769M, Apache-2.0)
  else → WHISPER_MODEL (default small)
Runtimes: a CTranslate2 model dir/name → faster-whisper; an HF id containing
'/' without a CT2 conversion → transformers pipeline over VAD windows;
indic-conformer → its own CTC path. All stay loaded across requests.

Devices: faster-whisper on CUDA when CTranslate2 can load cuBLAS 12 (see
pipeline/gpu.py), torch models via ``LyricsConfig.torch_device``.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

# Importing this first keeps huggingface_hub off the stalling xet backend (see
# pipeline/hf_setup.py) — this module is where every model download happens.
from pipeline import hf_setup  # noqa: F401
from pipeline.config import LyricsConfig
from pipeline.gpu import whisper_compute_type, whisper_device
from pipeline.hf_setup import repo_cache_state

logger = logging.getLogger(__name__)

#: ``progress(stage, fraction)`` hook used to report job progress to the UI.
Progress = Callable[[str, float], None] | None

SR = 16000

_fw_models: dict[str, Any] = {}
_hf_pipes: dict[str, Any] = {}
_conformer_models: dict[str, Any] = {}
_indic_transcribe: dict[str, Any] = {}

#: Bodhan AI / AI4Bharat Indic-Transcribe (Canary 1.2B, gated, Indic Open Model
#: License). Text-only output — word timing comes from the forced aligner.
INDIC_TRANSCRIBE_REPOS = ("bodhan-ai/indic-transcribe-core", "bodhan-ai/indic-transcribe-flex")

#: Progress band for model load + transcription, shared with lyrics_transcriber
#: (which hands us 0.45 and expects ~0.8 back before alignment).
_PCT_MODEL_READY = 0.48
_PCT_TRANSCRIBE = 0.50
_PCT_TRANSCRIBE_END = 0.78

_INITIAL_PROMPTS = {
    "hi": "यह एक हिंदी गाना है।",
    "ml": "ഇതൊരു മലയാളം ഗാനമാണ്.",
    "en": None,
}

#: Non-candidate languages win LID only when Whisper is this sure AND this many
#: times more confident than the best candidate.
_LID_OVERRIDE_PROB = 0.85
_LID_OVERRIDE_RATIO = 3.0

#: ISO-639-1 → notes for the recommendation table (eval).
MODEL_NOTES = {
    "adalat-ai/whisper-medium-ml-rmft": "ml primary (769M, Apache-2.0)",
    "adalat-ai/whisper-medium-hi-high-lr": "hi primary (769M, Apache-2.0)",
    "adalat-ai/whisper-small-ml-rmft": "ml fallback (244M)",
    "adalat-ai/whisper-small-hi-high-lr": "hi fallback (244M)",
    "thennal/whisper-medium-ml": "comparison (Apache-2.0)",
    "vasista22/whisper-hindi-large-v2": "comparison (1.5B — CPU-heavy)",
    "Sanat-agrwl/indic-crisperwhisper-hindi-v1": "comparison verbatim+timestamps (custom code, MIT)",
    "ai4bharat/indic-conformer-600m-multilingual": "one-model alt (MIT, gated, CTC/RNNT)",
}


def _report(progress: Progress, stage: str, pct: float) -> None:
    """Progress reporting must never break a job."""
    if not progress:
        return
    try:
        progress(stage, round(pct, 3))
    except Exception:
        pass


def fw_repo(name: str) -> str:
    """CTranslate2 model name → the HF repo faster-whisper itself resolves."""
    return name if "/" in name else f"Systran/faster-whisper-{name}"


def _announce_model(model_name: str, progress: Progress) -> None:
    """Report whether this run must download weights or just load them."""
    if Path(model_name).is_dir():
        _report(progress, "loading_model", _PCT_MODEL_READY - 0.03)
        return
    repo = fw_repo(model_name)
    cached, size = repo_cache_state(repo)
    if cached:
        logger.info("model cached %s (%s) — loading", repo, f"{size / 1e6:.0f} MB")
        _report(progress, "loading_model", _PCT_MODEL_READY - 0.03)
        return
    logger.warning(
        "first run with %s: downloading %s from the Hugging Face Hub "
        "(%s cached) — this happens once per model",
        model_name, repo, f"{size / 1e6:.0f} MB" if size else "nothing",
    )
    _report(progress, "downloading_model", _PCT_MODEL_READY - 0.03)


def load_stem(path: str | Path) -> np.ndarray:
    """16 kHz mono float32. Separation already writes exactly that, so the
    common case is a cheap soundfile read; anything else is resampled."""
    try:
        import soundfile as sf

        y, sr = sf.read(str(path), dtype="float32", always_2d=False)
        if sr == SR and y.ndim == 1:
            return y
    except Exception:
        pass
    import librosa

    y, _ = librosa.load(str(path), sr=SR, mono=True)
    return y.astype(np.float32)


def _evict_fw(keep: set[str]) -> None:
    """Free faster-whisper models not in ``keep`` (CTranslate2 releases VRAM
    when the model object is collected)."""
    import gc

    for name in [n for n in _fw_models if n not in keep]:
        logger.info("unloading faster-whisper model=%s", name)
        del _fw_models[name]
    gc.collect()


def _free_indic_transcribe() -> None:
    if _indic_transcribe:
        import gc

        logger.info("unloading Indic-Transcribe")
        _indic_transcribe.clear()
        gc.collect()
        try:
            import torch

            torch.cuda.empty_cache()
        except Exception:
            pass


def _get_fw_model(name: str, cfg: LyricsConfig):
    """Load (or reuse) a faster-whisper model.

    VRAM budget (4 GB GTX 1650): only the language-ID model and ONE ASR
    model stay resident — a hi job followed by an ml job used to stack two
    medium models next to demucs and the aligner and run out of memory.
    """
    if name in _fw_models:
        return _fw_models[name]
    from faster_whisper import WhisperModel

    _evict_fw(keep={cfg.lid_model})
    _free_indic_transcribe()
    device = whisper_device(cfg.whisper_device)
    compute = whisper_compute_type(device, cfg.whisper_compute_type)
    logger.info("loading faster-whisper model=%s device=%s compute=%s", name, device, compute)
    try:
        _fw_models[name] = WhisperModel(name, device=device, compute_type=compute)
    except (RuntimeError, ValueError) as exc:
        if device == "cpu":
            raise
        logger.warning("faster-whisper on %s failed (%s) — freeing all and retrying",
                       device, exc)
        _evict_fw(keep=set())
        try:
            _fw_models[name] = WhisperModel(name, device=device, compute_type=compute)
        except (RuntimeError, ValueError) as exc2:
            logger.warning("still failing (%s) — cpu int8", exc2)
            _fw_models[name] = WhisperModel(name, device="cpu", compute_type="int8")
    return _fw_models[name]


def _get_hf_pipe(model_id: str, cfg: LyricsConfig):
    if model_id in _hf_pipes:
        return _hf_pipes[model_id]
    from transformers import pipeline

    device = cfg.torch_device()
    kwargs: dict[str, Any] = {"model": model_id}
    if device.startswith("cuda"):
        import torch

        kwargs["torch_dtype"] = torch.float16
    if cfg.hf_token:
        kwargs["token"] = cfg.hf_token
    logger.info("loading transformers ASR model=%s device=%s", model_id, device)
    _hf_pipes[model_id] = pipeline("automatic-speech-recognition", device=device, **kwargs)
    return _hf_pipes[model_id]


# ── language ID (A1) ──────────────────────────────────────────────────────

def pick_language(
    detected: str, prob: float, all_probs: list[tuple[str, float]],
    candidates: tuple[str, ...],
) -> tuple[str, float]:
    """Bias Whisper LID toward the languages we serve.

    Pure function (unit-tested). Returns (language, probability)."""
    if not candidates or detected in candidates:
        return detected, prob
    probs = dict(all_probs)
    best = max(candidates, key=lambda c: probs.get(c, 0.0))
    best_p = probs.get(best, 0.0)
    if prob >= _LID_OVERRIDE_PROB and prob >= _LID_OVERRIDE_RATIO * best_p:
        return detected, prob
    logger.info("lid: %s (%.2f) outside candidates → %s (%.2f)", detected, prob, best, best_p)
    return best, best_p


def detect_language(y: np.ndarray, cfg: LyricsConfig) -> tuple[str | None, float]:
    """Vote over up to 4 voiced 30 s windows of the stem."""
    try:
        model = _get_fw_model(cfg.lid_model, cfg)
        # voiced audio only (energy gate on the stem, ≤ 120 s), then 4 votes
        voiced = [y[int(s * SR):int(e * SR)] for s, e in voiced_windows(y, 30.0)]
        clip = np.concatenate(voiced)[: 120 * SR] if voiced else y
        lang, prob, all_probs = model.detect_language(
            audio=clip, vad_filter=False,
            language_detection_segments=4, language_detection_threshold=0.5,
        )
        lang, prob = pick_language(lang, float(prob), list(all_probs), cfg.lang_candidates)
        logger.info("lid: language=%s p=%.2f (model=%s)", lang, prob, cfg.lid_model)
        return lang, prob
    except Exception as exc:
        logger.warning("language detection failed (%s) — model decides", exc)
        return None, 0.0


# ── voiced windows ────────────────────────────────────────────────────────
# Silero VAD is trained on SPEECH and misses sustained singing (measured: it
# marked 41 s of a 183 s ballad as voiced and Whisper lost half the lyrics).
# The input is already an isolated vocal stem, so plain energy is the right
# detector: instrumental stretches are near-silent there.

def voiced_windows(y: np.ndarray, max_len: float, *, hop_s: float = 0.05,
                   rel_db: float = 35.0, floor_db: float = -50.0,
                   bridge_s: float = 0.8, min_s: float = 0.3, pad_s: float = 0.2,
                   ) -> list[tuple[float, float]]:
    """Energy-gated voiced spans of the stem packed into windows ≤ max_len s.

    A frame is voiced when its RMS is within ``rel_db`` of the loud (95th
    percentile) level and above ``floor_db`` dBFS. Gaps < ``bridge_s`` are
    bridged, blips < ``min_s`` dropped, spans padded by ``pad_s``. Pure
    numpy (unit-tested)."""
    hop = max(1, int(hop_s * SR))
    n = len(y) // hop
    if n == 0:
        return []
    frames = y[: n * hop].reshape(n, hop)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1)) + 1e-10
    db = 20 * np.log10(rms)
    thr = max(floor_db, float(np.percentile(db, 95)) - rel_db)
    active = db > thr
    spans: list[list[float]] = []
    i = 0
    while i < n:
        if active[i]:
            j = i
            while j < n and active[j]:
                j += 1
            s, e = i * hop_s, j * hop_s
            if spans and s - spans[-1][1] < bridge_s:
                spans[-1][1] = e
            else:
                spans.append([s, e])
            i = j
        else:
            i += 1
    dur = len(y) / SR
    spans = [[max(0.0, s - pad_s), min(dur, e + pad_s)] for s, e in spans if e - s >= min_s]
    windows: list[tuple[float, float]] = []
    for s, e in spans:
        while e - s > max_len:  # long voiced run → hard split
            windows.append((s, s + max_len))
            s += max_len
        if windows and e - windows[-1][0] <= max_len and s - windows[-1][1] < 1.5:
            windows[-1] = (windows[-1][0], e)
        else:
            windows.append((s, e))
    return [(round(s, 3), round(e, 3)) for s, e in windows]


# ── post-processing ───────────────────────────────────────────────────────

def _drop_repeat_loops(words: list[dict[str, Any]], n: int = 4) -> list[dict[str, Any]]:
    """Drop exact n-gram repeats back-to-back (Whisper music hallucination)."""
    if len(words) < 2 * n:
        return words
    out = list(words[:n])
    i = n
    while i < len(words):
        window = [w["word"] for w in words[i:i + n]]
        prev = [w["word"] for w in out[-n:]]
        if len(window) == n and window == prev:
            j = i + n
            while [w["word"] for w in words[j:j + n]] == prev and j < len(words):
                j += n
            logger.debug("asr: dropped repeat loop %r x%d", prev, (j - i) // n + 1)
            i = j
            continue
        out.append(words[i])
        i += 1
    return out


def _dedupe_seams(words: list[dict[str, Any]], overlap: float = 0.0) -> list[dict[str, Any]]:
    """Drop words starting inside the previous word's span (window seams,
    duplicated decodes). ``overlap`` kept for call compatibility."""
    out: list[dict[str, Any]] = []
    for w in sorted(words, key=lambda x: (x["timestamp"], x.get("end", 0))):
        if out and w["timestamp"] < out[-1].get("end", out[-1]["timestamp"]) - 0.05:
            continue
        out.append(w)
    return out


# ── runtimes ──────────────────────────────────────────────────────────────

def _transcribe_fw(
    y: np.ndarray, lang: str | None, model_name: str, cfg: LyricsConfig,
    on_progress: Callable[[float], None] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    from faster_whisper import BatchedInferencePipeline

    model = _get_fw_model(model_name, cfg)
    pipe = BatchedInferencePipeline(model)
    fine_tune = "/" in model_name  # HF id or local CT2 conversion dir
    prompt = _INITIAL_PROMPTS.get(lang or "")
    duration = max(1e-6, len(y) / SR)
    # Indic scripts are token-dense: shorter windows avoid the 448-token cap.
    chunk = 30 if lang in (None, "en") else 20
    windows = voiced_windows(y, float(chunk))
    if not windows:
        return [], [], lang
    segments, info = pipe.transcribe(
        y,
        language=lang,
        task="transcribe",
        batch_size=cfg.asr_batch_size,
        beam_size=cfg.asr_beam_size,
        word_timestamps=True,
        clip_timestamps=[{"start": s, "end": e} for s, e in windows],
        chunk_length=chunk,
        no_repeat_ngram_size=3,
        temperature=[0.0, 0.2, 0.4],
        compression_ratio_threshold=2.4,
        log_prob_threshold=-1.0,
        no_speech_threshold=0.6,
        # Script prompt only for stock multilingual models (stops Devanagari /
        # Malayalam drifting into romanisation). Fine-tunes are already
        # language-locked, and a prompt can be echoed back as a "lyric" in a
        # quiet window — measured with the hi fine-tune.
        initial_prompt=None if fine_tune else prompt,
    )
    words: list[dict[str, Any]] = []
    raw_lines: list[dict[str, Any]] = []
    for segm in segments:
        text = (segm.text or "").replace("\ufffd", "").strip()
        if prompt and text == prompt:  # echoed prompt, not a lyric
            continue
        if text:
            raw_lines.append({
                "timestamp": round(float(segm.start or 0.0), 3),
                "end": round(float(segm.end or 0.0), 3),
                "text": text,
            })
        for w in segm.words or []:
            # word timestamps split multi-byte (Malayalam/Devanagari) tokens
            # at byte boundaries → U+FFFD fragments; drop them
            token = (w.word or "").replace("\ufffd", "").strip()
            if token:
                words.append({
                    "timestamp": round(float(w.start or 0.0), 3),
                    "end": round(float(w.end or 0.0), 3),
                    "word": token,
                    "probability": round(float(getattr(w, "probability", 0.0) or 0.0), 3),
                })
        if on_progress:
            on_progress(min(1.0, float(segm.end or 0.0) / duration))
    return words, raw_lines, getattr(info, "language", None) or lang


def _transcribe_hf(
    y: np.ndarray, lang: str | None, model_id: str, cfg: LyricsConfig,
    on_progress: Callable[[float], None] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    pipe = _get_hf_pipe(model_id, cfg)
    windows = voiced_windows(y, float(min(30, max(10, cfg.asr_chunk_length_s + 8))))
    words: list[dict[str, Any]] = []
    raw_lines: list[dict[str, Any]] = []
    for i, (s, e) in enumerate(windows):
        seg = y[int(s * SR):int(e * SR)]
        if not len(seg):
            continue
        generate_kwargs: dict[str, Any] = {"task": "transcribe"}
        if lang:
            generate_kwargs["language"] = lang
        out = pipe({"raw": seg, "sampling_rate": SR},
                   generate_kwargs=generate_kwargs, return_timestamps="word")
        text = (out.get("text") or "").strip() if isinstance(out, dict) else ""
        if text:
            raw_lines.append({"timestamp": round(s, 3), "end": round(e, 3), "text": text})
        chunk_words = []
        for ch in (out.get("chunks") or [] if isinstance(out, dict) else []):
            ts = ch.get("timestamp")
            tok = (ch.get("text") or "").strip()
            if not tok or not ts:
                continue
            chunk_words.append({
                "timestamp": round(s + float(ts[0] or 0.0), 3),
                "end": round(s + float(ts[1] or ts[0] or 0.0), 3),
                "word": tok,
            })
        if not chunk_words and text:  # segment text only — split evenly
            toks = text.split()
            per = max(0.2, (e - s) / max(1, len(toks)))
            chunk_words = [{"timestamp": round(s + k * per, 3),
                            "end": round(s + (k + 1) * per, 3), "word": t}
                           for k, t in enumerate(toks)]
        words.extend(chunk_words)
        if on_progress:
            on_progress((i + 1) / max(1, len(windows)))
    return words, raw_lines, lang


def _transcribe_conformer(
    y: np.ndarray, lang_hint: str | None, cfg: LyricsConfig,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    """ai4bharat indic-conformer (MIT, gated). ``model(wav, lang, decoding)``
    API per the model card. CTC decode; no word timings → even split (the
    aligner upgrades them)."""
    import torch
    from transformers import AutoModel

    key = "ai4bharat/indic-conformer-600m-multilingual"
    if key not in _conformer_models:
        logger.info("loading indic-conformer (trust_remote_code)")
        _conformer_models[key] = AutoModel.from_pretrained(
            key, trust_remote_code=True, token=cfg.hf_token or None
        )
    model = _conformer_models[key]
    wav = torch.from_numpy(y).unsqueeze(0)
    lang = lang_hint if lang_hint in ("hi", "ml") else "hi"
    with torch.no_grad():
        text = model(wav, lang, "ctc")
    text = (text[0] if isinstance(text, (list, tuple)) else str(text)).strip()
    duration = len(y) / SR
    toks = text.split()
    per = duration / max(1, len(toks)) if duration else 0.4
    words = [{"timestamp": round(i * per, 3), "end": round((i + 1) * per, 3), "word": tok}
             for i, tok in enumerate(toks)]
    lines = [{"timestamp": 0.0, "end": round(duration, 3), "text": text}] if text else []
    return words, lines, lang


def _get_indic_transcribe(repo: str, cfg: LyricsConfig):
    """Load Indic-Transcribe from its (gated) repo. The model code ships inside
    the repo (reviewed: no network/subprocess/pickle use); the NeMo checkpoint
    under nemo/ is not downloaded."""
    if repo in _indic_transcribe:
        return _indic_transcribe[repo]
    import sys

    import torch
    from huggingface_hub import snapshot_download

    _evict_fw(keep=set())  # 1.2B params: make room on a 4 GB card
    _free_indic_transcribe()
    path = snapshot_download(repo, ignore_patterns=["nemo/*"],
                             token=cfg.hf_token or None)
    if path not in sys.path:
        sys.path.insert(0, path)
    from indic_transcribe import IndicTranscribe

    device = cfg.torch_device()
    # The checkpoint defaults to bf16 on GPU; Turing cards (GTX 16xx/RTX 20xx)
    # have no bf16, so use fp16 there (~2.4 GB) and fp32 on CPU.
    dtype = torch.float32
    if device.startswith("cuda"):
        dtype = (torch.bfloat16 if torch.cuda.is_bf16_supported(including_emulation=False)
                 else torch.float16)
    logger.info("loading Indic-Transcribe %s device=%s dtype=%s", repo, device, dtype)
    _indic_transcribe[repo] = IndicTranscribe.from_pretrained(path, device=device, dtype=dtype)
    return _indic_transcribe[repo]


def _transcribe_indic_transcribe(
    y: np.ndarray, lang: str | None, repo: str, cfg: LyricsConfig,
    on_progress: Callable[[float], None] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    """Decode each voiced window (≤ 30 s — the checkpoint's training length).

    Returns window-level ``raw_lines`` (exact spans) and rough words spread
    evenly inside each window; the caller aligns per window for real timing.
    """
    asr = _get_indic_transcribe(repo, cfg)
    _to_device(asr, asr.device)
    try:
        return _decode_windows(asr, y, lang, on_progress)
    finally:
        # 2.4 GB fp16 must leave the GPU before the aligner (1.2 GB) runs on a
        # 4 GB card; parking it in RAM makes the next job's reload ~1 s.
        if str(asr.device).startswith("cuda"):
            _to_device(asr, "cpu")


def _to_device(asr: Any, device: str) -> None:
    import torch

    if next(asr.model.parameters()).device.type != torch.device(device).type:
        asr.model.to(device)
        if device == "cpu":
            torch.cuda.empty_cache()


def _decode_windows(
    asr: Any, y: np.ndarray, lang: str | None,
    on_progress: Callable[[float], None] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    windows = voiced_windows(y, 30.0)
    words: list[dict[str, Any]] = []
    raw_lines: list[dict[str, Any]] = []
    detected = lang
    for i, (s, e) in enumerate(windows):
        seg = y[int(s * SR):int(e * SR)]
        if len(seg) < SR // 4:
            continue
        text = asr.transcribe(seg, lang=detected) if detected else None
        if text is None:  # no language given: let the model identify it once
            text, lid = asr.transcribe(seg, lang=None, return_lid=True)
            detected = lid.get("lang") or detected
        text = (text or "").strip()
        if text:
            raw_lines.append({"timestamp": round(s, 3), "end": round(e, 3), "text": text})
            toks = text.split()
            per = (e - s) / max(1, len(toks))
            words.extend({"timestamp": round(s + k * per, 3),
                          "end": round(s + (k + 1) * per, 3), "word": t}
                         for k, t in enumerate(toks))
        if on_progress:
            on_progress((i + 1) / max(1, len(windows)))
    return words, raw_lines, detected


def transcribe_asr(
    vocal_path: str | Path, language: str | None = None,
    cfg: LyricsConfig | None = None,
    progress: Progress = None,
    audio: np.ndarray | None = None,
) -> dict[str, Any]:
    """Music-tuned ASR over an isolated vocal stem (16 kHz mono).

    ``audio`` (optional) is the already-decoded stem; ``progress`` receives
    ``(stage, fraction)`` updates for LID, model load and transcription.
    """
    from lyrics_transcriber import _lines_from_words  # reuse line grouping

    cfg = cfg or LyricsConfig.from_env()
    lang = (language or "").strip().lower() or None
    t0 = time.time()
    model_name = cfg.asr_model_for(lang)
    try:
        y = audio if audio is not None else load_stem(vocal_path)
        lang_prob: float | None = None
        if lang is None:
            _report(progress, "detecting_language", _PCT_MODEL_READY - 0.04)
            lang, lang_prob = detect_language(y, cfg)
            model_name = cfg.asr_model_for(lang)
        logger.info("asr model=%s language=%s", model_name, lang or "auto")

        def _progress(frac: float) -> None:
            _report(progress, "transcribing",
                    _PCT_TRANSCRIBE + (_PCT_TRANSCRIBE_END - _PCT_TRANSCRIBE) * frac)

        if model_name not in INDIC_TRANSCRIBE_REPOS:
            _announce_model(model_name, progress)
        timing = "word"
        if model_name in INDIC_TRANSCRIBE_REPOS:
            words, raw_lines, detected = _transcribe_indic_transcribe(
                y, lang, model_name, cfg, _progress)
            timing = "window"  # text only: words must be aligned per window
        elif model_name == "ai4bharat/indic-conformer-600m-multilingual":
            words, raw_lines, detected = _transcribe_conformer(y, lang, cfg)
        elif "/" in model_name and not Path(model_name).is_dir():  # HF fine-tune
            words, raw_lines, detected = _transcribe_hf(y, lang, model_name, cfg, _progress)
        else:  # faster-whisper / CTranslate2 name or local dir
            words, raw_lines, detected = _transcribe_fw(y, lang, model_name, cfg, _progress)
        _report(progress, "transcribing", _PCT_TRANSCRIBE_END)
        if timing == "word":
            words = _dedupe_seams(words)
        words = _drop_repeat_loops(words)
        lines = _lines_from_words(words, raw_lines)
        logger.info("asr done model=%s words=%d lines=%d in %.1fs",
                    model_name, len(words), len(lines), time.time() - t0)
        return {
            "lyrics": words, "lines": lines, "segments": raw_lines,
            "language": detected or lang, "language_prob": lang_prob,
            "error": None, "model": model_name,
            "source": "asr", "timing": timing,
        }
    except Exception as exc:
        logger.exception("ASR failed model=%s", model_name)
        return {"lyrics": [], "lines": [], "segments": [], "language": lang,
                "error": str(exc)[:500], "model": model_name, "source": "asr"}
