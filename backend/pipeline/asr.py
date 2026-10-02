"""
pipeline/asr.py
---------------
Phase 3 — language-specific ASR with music-tuned chunking.

Routing (``LyricsConfig.asr_model_for``):
  ml → adalat-ai/whisper-medium-ml-rmft (769M, Apache-2.0, verified)
  hi → adalat-ai/whisper-medium-hi-high-lr (769M, Apache-2.0, verified)
  small fallbacks: adalat-ai/whisper-small-ml-rmft / -hi-high-lr (244M)
Comparison presets (env-overridable, benchmark don't assume):
  thennal/whisper-medium-ml, vasista22/whisper-hindi-large-v2 (1.5B),
  Sanat-agrwl/indic-crisperwhisper-hindi-v1 (was user71/… — ID corrected,
    custom retok code, wire as transformers-pipeline only),
  ai4bharat/indic-conformer-600m-multilingual (MIT, gated — needs HF_TOKEN,
    trust_remote_code, ``model(wav, lang, 'ctc'|'rnnt')`` API).

Runtimes: IDs containing '/' load via transformers ASR pipeline (HF
fine-tunes are transformers checkpoints, not CTranslate2); plain names
(small, large-v3-turbo) use faster-whisper. Both kept loaded across requests.

Chunking: 12 s windows (10–15 s per brief — Indic scripts are token-dense and
30 s windows risk the 448-token truncation), ~2 s seam dedup, explicit
``language`` + ``task='transcribe'``. Near-silent chunks (vocal-stem RMS below
threshold) are skipped to suppress instrumental hallucinations; repeated
n-gram loops are dropped.

Speed note: converting a chosen HF checkpoint to CTranslate2
(``ct2-transformers-converter --model <id> --quantization int8``) for
faster-whisper gives large size/speed wins — validate CER on eval/ before
shipping a quantised model.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from pipeline.config import LyricsConfig

logger = logging.getLogger(__name__)

_fw_models: dict[str, Any] = {}
_hf_pipes: dict[str, Any] = {}
_conformer_models: dict[str, Any] = {}

_INITIAL_PROMPTS = {
    "hi": "यह एक हिंदी गाना है।",
    "ml": "ഇതൊരു മലയാളം ഗാനമാണ്.",
    "en": None,
}

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


def _get_fw_model(name: str, cfg: LyricsConfig):
    if name in _fw_models:
        return _fw_models[name]
    from faster_whisper import WhisperModel

    logger.info("loading faster-whisper model=%s device=%s compute=%s",
                name, cfg.whisper_device, cfg.whisper_compute_type)
    _fw_models[name] = WhisperModel(
        name, device=cfg.whisper_device, compute_type=cfg.whisper_compute_type
    )
    return _fw_models[name]


def _get_hf_pipe(model_id: str, cfg: LyricsConfig):
    if model_id in _hf_pipes:
        return _hf_pipes[model_id]
    from transformers import pipeline

    device: int | str = -1
    if cfg.whisper_device.startswith("cuda"):
        device = 0
    logger.info("loading transformers ASR model=%s device=%s", model_id, device)
    kwargs: dict[str, Any] = {"model": model_id}
    if cfg.hf_token:
        kwargs["token"] = cfg.hf_token
    _hf_pipes[model_id] = pipeline(
        "automatic-speech-recognition", device=device, **kwargs
    )
    return _hf_pipes[model_id]


def _chunk_spans(duration: float, length: float, overlap: float) -> list[tuple[float, float]]:
    spans: list[tuple[float, float]] = []
    start = 0.0
    step = max(1.0, length - overlap)
    while start < duration:
        spans.append((start, min(duration, start + length)))
        if start + length >= duration:
            break
        start += step
    return spans


def _audible_spans(
    vocal_path: Path, duration: float, length: float, overlap: float, threshold: float
) -> list[tuple[float, float]]:
    """Drop near-silent (instrumental) windows by vocal-stem RMS energy."""
    try:
        import librosa
        import numpy as np

        y, sr = librosa.load(str(vocal_path), sr=16000, mono=True)
        spans = _chunk_spans(duration, length, overlap)
        keep: list[tuple[float, float]] = []
        for s, e in spans:
            seg = y[int(s * sr):int(e * sr)]
            rms = float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0
            if rms >= threshold:
                keep.append((s, e))
        if not keep:
            logger.info("asr: all chunks below RMS %.3f — keeping loudest", threshold)
            rms_all = [
                (float(np.sqrt(np.mean(y[int(s * sr):int(e * sr)] ** 2)))
                 if int(e * sr) > int(s * sr) else 0.0, (s, e))
                for s, e in spans
            ]
            rms_all.sort(reverse=True)
            keep = [rms_all[0][1]] if rms_all else spans
        logger.info("asr: %d/%d chunks audible", len(keep), len(spans))
        return keep
    except Exception as exc:
        logger.debug("rms gating unavailable (%s) — keeping all chunks", exc)
        return _chunk_spans(duration, length, overlap)


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


def _dedupe_seams(
    words: list[dict[str, Any]], overlap: float
) -> list[dict[str, Any]]:
    """Overlapping windows re-decode the seam — drop words starting inside the
    previous word's span (same timebase, ~overlap tolerance)."""
    out: list[dict[str, Any]] = []
    for w in sorted(words, key=lambda x: (x["timestamp"], x.get("end", 0))):
        if out and w["timestamp"] < out[-1].get("end", out[-1]["timestamp"]) - 0.05:
            continue
        out.append(w)
    return out


def _transcribe_fw(
    vocal_path: Path, lang_hint: str | None, spans: list[tuple[float, float]],
    model_name: str, cfg: LyricsConfig,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    import tempfile

    import soundfile as sf
    import librosa

    model = _get_fw_model(model_name, cfg)
    y_full, sr_full = librosa.load(str(vocal_path), sr=16000, mono=True)
    words: list[dict[str, Any]] = []
    raw_lines: list[dict[str, Any]] = []
    detected: str | None = None
    for s, e in spans:
        seg = y_full[int(s * sr_full):int(e * sr_full)]
        if not len(seg):
            continue
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            sf.write(tmp.name, seg, 16000)
            chunk_path = tmp.name
        try:
            segments, info = model.transcribe(
                chunk_path,
                word_timestamps=True,
                language=lang_hint,
                task="transcribe",
                vad_filter=True,
                beam_size=5,
                condition_on_previous_text=False,
                no_repeat_ngram_size=3,
                hallucination_silence_threshold=2.0,
                chunk_length=cfg.asr_chunk_length_s,
                vad_parameters={"min_silence_duration_ms": 1000, "speech_pad_ms": 200},
                initial_prompt=_INITIAL_PROMPTS.get(lang_hint or ""),
            )
            detected = detected or getattr(info, "language", None)
            for segm in segments:
                text = (segm.text or "").strip()
                if text:
                    raw_lines.append({
                        "timestamp": round(s + float(segm.start or 0.0), 3),
                        "end": round(s + float(segm.end or 0.0), 3),
                        "text": text,
                    })
                for w in segm.words or []:
                    token = (w.word or "").strip()
                    if token:
                        words.append({
                            "timestamp": round(s + float(w.start or 0.0), 3),
                            "end": round(s + float(w.end or 0.0), 3),
                            "word": token,
                        })
        finally:
            try:
                Path(chunk_path).unlink(missing_ok=True)
            except OSError:
                pass
    return words, raw_lines, detected


def _transcribe_hf(
    vocal_path: Path, lang_hint: str | None, spans: list[tuple[float, float]],
    model_id: str, cfg: LyricsConfig,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    import tempfile

    import soundfile as sf
    import librosa

    pipe = _get_hf_pipe(model_id, cfg)
    lang_3 = {"hi": "hin", "ml": "mal"}.get(lang_hint or "", None)
    y_full, _ = librosa.load(str(vocal_path), sr=16000, mono=True)
    words: list[dict[str, Any]] = []
    raw_lines: list[dict[str, Any]] = []
    for s, e in spans:
        seg = y_full[int(s * 16000):int(e * 16000)]
        if not len(seg):
            continue
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            sf.write(tmp.name, seg, 16000)
            chunk_path = tmp.name
        try:
            generate_kwargs: dict[str, Any] = {"task": "transcribe"}
            if lang_hint:
                generate_kwargs["language"] = lang_hint
            out = pipe(
                chunk_path,
                chunk_length_s=cfg.asr_chunk_length_s,
                generate_kwargs=generate_kwargs,
                return_timestamps="word" if lang_3 else True,
            )
            text = (out.get("text") or "").strip() if isinstance(out, dict) else ""
            if text:
                raw_lines.append({"timestamp": round(s, 3), "end": round(e, 3), "text": text})
            for ch in (out.get("chunks") or [] if isinstance(out, dict) else []):
                ts = ch.get("timestamp")
                tok = (ch.get("text") or "").strip()
                if not tok or not ts:
                    continue
                words.append({
                    "timestamp": round(s + float(ts[0] or 0.0), 3),
                    "end": round(s + float(ts[1] or ts[0] or 0.0), 3),
                    "word": tok,
                })
        finally:
            try:
                Path(chunk_path).unlink(missing_ok=True)
            except OSError:
                pass
    if not words:  # pipeline gave segment text only — split evenly per chunk
        for line in raw_lines:
            toks = line["text"].split()
            per = max(0.2, (line["end"] - line["timestamp"]) / max(1, len(toks)))
            for i, tok in enumerate(toks):
                st = line["timestamp"] + i * per
                words.append({"timestamp": round(st, 3), "end": round(st + per, 3), "word": tok})
    return words, raw_lines, lang_hint


def _transcribe_conformer(
    vocal_path: Path, lang_hint: str | None, cfg: LyricsConfig,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    """ai4bharat indic-conformer (MIT, gated). ``model(wav, lang, decoding)``
    API verified against the model card. CTC decode; word timings unavailable
    → even-split lines (Phase 4 upgrades them)."""
    import torch
    import torchaudio
    from transformers import AutoModel

    key = "ai4bharat/indic-conformer-600m-multilingual"
    if key not in _conformer_models:
        logger.info("loading indic-conformer (trust_remote_code)")
        _conformer_models[key] = AutoModel.from_pretrained(
            key, trust_remote_code=True, token=cfg.hf_token or None
        )
    model = _conformer_models[key]
    wav, sr = torchaudio.load(str(vocal_path))
    wav = torch.mean(wav, dim=0, keepdim=True)
    if sr != 16000:
        wav = torchaudio.transforms.Resample(orig_freq=sr, new_freq=16000)(wav)
    lang = lang_hint if lang_hint in ("hi", "ml") else "hi"
    with torch.no_grad():
        text = model(wav, lang, "ctc")
    text = (text[0] if isinstance(text, (list, tuple)) else str(text)).strip()
    try:
        import librosa

        duration = float(librosa.get_duration(path=str(vocal_path)))
    except Exception:
        duration = 0.0
    toks = text.split()
    words = []
    per = duration / max(1, len(toks)) if duration else 0.4
    for i, tok in enumerate(toks):
        words.append({"timestamp": round(i * per, 3), "end": round((i + 1) * per, 3), "word": tok})
    lines = [{"timestamp": 0.0, "end": round(duration, 3), "text": text}] if text else []
    return words, lines, lang


def transcribe_asr(
    vocal_path: str | Path, language: str | None = None,
    cfg: LyricsConfig | None = None,
) -> dict[str, Any]:
    """Chunked, music-tuned ASR over an isolated vocal stem (16 kHz mono)."""
    from lyrics_transcriber import _lines_from_words  # reuse line grouping

    cfg = cfg or LyricsConfig.from_env()
    vocal_path = Path(vocal_path)
    lang_hint = (language or "").strip().lower() or None
    model_name = cfg.asr_model_for(lang_hint)
    t0 = time.time()
    logger.info("asr model=%s language=%s chunk=%ds+%ds",
                model_name, lang_hint or "auto",
                cfg.asr_chunk_length_s, cfg.asr_chunk_overlap_s)
    try:
        try:
            import librosa

            duration = float(librosa.get_duration(path=str(vocal_path)))
        except Exception:
            duration = 0.0
        spans = _audible_spans(
            vocal_path, duration or 1.0,
            float(cfg.asr_chunk_length_s), float(cfg.asr_chunk_overlap_s),
            cfg.asr_rms_threshold,
        )
        if model_name == "ai4bharat/indic-conformer-600m-multilingual":
            words, raw_lines, detected = _transcribe_conformer(vocal_path, lang_hint, cfg)
        elif "/" in model_name:  # HF transformers fine-tune
            words, raw_lines, detected = _transcribe_hf(vocal_path, lang_hint, spans, model_name, cfg)
        else:  # stock faster-whisper / CTranslate2 id
            words, raw_lines, detected = _transcribe_fw(vocal_path, lang_hint, spans, model_name, cfg)
        words = _dedupe_seams(words, float(cfg.asr_chunk_overlap_s))
        words = _drop_repeat_loops(words)
        lines = _lines_from_words(words, raw_lines)
        logger.info("asr done model=%s words=%d lines=%d in %.1fs",
                    model_name, len(words), len(lines), time.time() - t0)
        return {
            "lyrics": words, "lines": lines,
            "language": detected or lang_hint,
            "error": None, "model": model_name,
            "source": "asr",
        }
    except Exception as exc:
        logger.exception("ASR failed model=%s", model_name)
        return {"lyrics": [], "lines": [], "language": None,
                "error": str(exc)[:500], "model": model_name, "source": "asr"}
