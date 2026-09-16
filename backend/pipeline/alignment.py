"""
pipeline/alignment.py
---------------------
Phase 4 — CTC forced alignment for word-level timing. Whisper word stamps come
from cross-attention DTW on a coarse token grid — too loose for karaoke-style
highlighting against the chord grid. We re-align whichever text we have
(LRCLIB or ASR) with ``ctc-forced-aligner`` (MahmoudAshraf97) wrapping Meta's
MMS aligner (1000+ languages).

Verified API (repo README + PyPI 1.0.2): ``load_alignment_model``,
``generate_emissions``, ``preprocess_text(text, romanize=True,
language=...)``, ``get_alignments``, ``get_spans``, ``postprocess_results``.
Non-Latin scripts MUST be romanised (``romanize=True``); language codes are
ISO-639-3 (``hin``/``mal``/``eng`` — not ``hi``/``ml``). We keep an
index mapping romanised tokens → native-script words and display native.

Timebase: seconds from 0 on the same audio file the chord stage analysed
(``librosa.load`` origin) — see ``test_pipeline_alignment.py``.

⚠️ LICENSING: the default MMS aligner weights are CC-BY-NC-4.0
(non-commercial). Fine for a free/personal project, a blocker for commercial
use — see LICENSE-NOTES.md. The backend is swappable via ``ALIGN_FN``.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable

from pipeline.config import LyricsConfig

logger = logging.getLogger(__name__)

_ISO3 = {"hi": "hin", "ml": "mal", "en": "eng"}
_MAX_WORD_S = 4.0

_model_cache: dict[str, Any] = {}

# Swappable aligner backend (commercial-safe alternative drops in here).
ALIGN_FN: Callable[..., list[dict[str, Any]] | None] | None = None


def _get_model(cfg: LyricsConfig):
    if "mms" in _model_cache:
        return _model_cache["mms"]
    import torch
    from ctc_forced_aligner import load_alignment_model

    device = "cuda" if cfg.whisper_device.startswith("cuda") and torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    logger.info("loading alignment model=%s device=%s", cfg.alignment_model, device)
    _model_cache["mms"] = load_alignment_model(device, dtype)
    return _model_cache["mms"]


def _native_word_list(
    lines: list[dict[str, Any]] | None, words: list[dict[str, Any]] | None,
    text: str | None,
) -> tuple[list[str], list[dict[str, Any]]]:
    if words:
        return [w.get("word", "") for w in words], []
    if lines:
        toks: list[str] = []
        for line in lines:
            toks.extend(line.get("text", "").split())
        return toks, lines
    return (text or "").split(), []


def align(
    vocal_stem_path: str | Path,
    text: str | None = None,
    language: str | None = None,
    *,
    lines: list[dict[str, Any]] | None = None,
    words: list[dict[str, Any]] | None = None,
    cfg: LyricsConfig | None = None,
) -> dict[str, Any]:
    """Return ``{words: [{word, timestamp, end, confidence}], lines, backend,
    error}`` on the chord timebase. Never raises — falls back to even-split."""
    from pipeline.lyrics_lookup import words_even_split

    cfg = cfg or LyricsConfig.from_env()
    vocal_stem_path = Path(vocal_stem_path)
    lang3 = _ISO3.get((language or "").lower(), "eng")
    native_words, src_lines = _native_word_list(lines, words, text)
    native_words = [w for w in native_words if w]
    if not native_words:
        return {"words": [], "lines": lines or [], "backend": "none", "error": "empty text"}

    fallback_lines = src_lines or [
        {"timestamp": 0.0, "end": 0.0, "text": " ".join(native_words)}
    ]
    if not cfg.alignment_enabled:
        return {"words": words_even_split(fallback_lines), "lines": fallback_lines,
                "backend": "even-split", "error": "disabled"}
    if ALIGN_FN is not None:
        try:
            custom = ALIGN_FN(vocal_stem_path, native_words, lang3)
            if custom:
                return {"words": custom, "lines": fallback_lines,
                        "backend": "custom", "error": None}
        except Exception as exc:
            logger.warning("custom aligner failed (%s)", exc)

    t0 = time.time()
    try:
        import torch  # noqa: F401
        from ctc_forced_aligner import (
            generate_emissions,
            get_alignments,
            get_spans,
            load_audio,
            postprocess_results,
            preprocess_text,
        )

        model, tokenizer = _get_model(cfg)
        waveform = load_audio(str(vocal_stem_path), model.dtype, model.device)
        emissions, stride = generate_emissions(model, waveform, batch_size=4)
        joined = " ".join(native_words)
        tokens_starred, text_starred = preprocess_text(joined, romanize=True, language=lang3)
        segments, scores, blank = get_alignments(emissions, tokens_starred, tokenizer)
        spans = get_spans(tokens_starred, segments, blank)
        aligned = postprocess_results(text_starred, spans, stride, scores)

        roman_tokens = text_starred.split()
        n = min(len(roman_tokens), len(native_words))
        if len(roman_tokens) != len(native_words):
            logger.warning("align token-count mismatch roman=%d native=%d — truncating",
                           len(roman_tokens), len(native_words))
        try:
            import librosa

            duration = float(librosa.get_duration(path=str(vocal_stem_path)))
        except Exception:
            duration = float("inf")

        out: list[dict[str, Any]] = []
        prev_end = 0.0
        low_conf = 0
        for i in range(n):
            seg = aligned[i] if i < len(aligned) else {}
            s = max(float(seg.get("start", prev_end)), prev_end)  # monotonic
            e = float(seg.get("end", s + 0.3))
            e = min(max(e, s + 0.05), s + _MAX_WORD_S, duration)
            conf = float(seg.get("score", seg.get("confidence", 0.0)) or 0.0)
            if conf < 0.3:
                low_conf += 1
            out.append({"word": native_words[i], "timestamp": round(s, 3),
                        "end": round(e, 3), "confidence": round(conf, 3)})
            prev_end = e
        logger.info("align ok lang=%s words=%d low_conf=%d in %.1fs",
                    lang3, len(out), low_conf, time.time() - t0)
        # Regroup lines from aligned words when caller gave plain text.
        out_lines = src_lines
        if not words and text and not lines:
            from lyrics_transcriber import _lines_from_words

            raw = [{"timestamp": 0.0, "end": duration if duration != float("inf") else 0.0,
                    "text": joined}]
            out_lines = _lines_from_words(
                [{"timestamp": w["timestamp"], "end": w["end"], "word": w["word"]} for w in out],
                raw,
            )
        return {"words": out, "lines": out_lines, "backend": "mms-ctc",
                "error": f"{low_conf} low-confidence words" if low_conf else None}
    except ImportError:
        logger.info("ctc-forced-aligner not installed — even-split fallback")
        return {"words": words_even_split(fallback_lines), "lines": fallback_lines,
                "backend": "even-split", "error": "aligner not installed"}
    except Exception as exc:
        logger.warning("alignment failed (%s) — even-split fallback", exc)
        return {"words": words_even_split(fallback_lines), "lines": fallback_lines,
                "backend": "even-split", "error": str(exc)[:300]}
