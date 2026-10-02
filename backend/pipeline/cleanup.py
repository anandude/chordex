"""
pipeline/cleanup.py
-------------------
Phase 5 — display-layer post-processing. Both steps optional, config-gated,
and NEVER applied to LRCLIB-sourced lyrics (already correct).

5a. LLM cleanup: Indic ASR gets phonemes right and orthography wrong. The
    repair prompt includes raw transcript + language + metadata, instructs the
    model to preserve uncertain content verbatim, and marks suspected nonsense
    with ``[?]`` rather than inventing fluent lyrics. No LLM provider is wired
    in this repo, so cleanup runs through an injectable ``LLM_FN`` (tests +
    future provider hook); when unset and enabled, it degrades to a no-op that
    keeps the raw text. Pre-cleanup text is always stored alongside for diffing;
    changed lines should be re-aligned by the caller.

5b. Romanisation (Manglish/Hinglish above chord symbols): two backends.
    Default ``indic`` uses ``indic-transliteration`` (pure Python, MIT) via
    ``sanscript.transliterate`` — always available, no model download.
    ``xlit`` uses IndicXlit (``ai4bharat-transliteration`` 1.1.3, MIT, 11M
    params; API verified: ``XlitEngine(src_script_type="indic")`` →
    ``translit_sentence(indic_sentence, lang_code)``) but is CURRENTLY BLOCKED:
    its transformer runtime imports fairseq, which is fundamentally broken on
    Python 3.11 (mutable dataclass defaults in configs.py). Revisit on a
    Python upgrade. Select via ``LYRICS_ROMAN_BACKEND=indic|xlit``.
    Display toggle only — canonical storage stays native-script; per-line cache.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from pipeline.config import LyricsConfig

logger = logging.getLogger(__name__)

# Injectable LLM hook: LLM_FN(prompt, *, language, metadata) -> cleaned text.
LLM_FN: Callable[..., str] | None = None

_xlit_engine: Any = None


CLEANUP_PROMPT = """You are fixing an automatic transcription of song lyrics \
in {language}{meta}. Repair spelling and word boundaries and restore line \
breaks. RULES: (1) If a line is garbled and you are not confident, keep it \
verbatim and append [?]. (2) NEVER invent fluent lyrics to replace uncertain \
content. (3) Keep the same number of lines and order. (4) Output only the \
corrected lyrics, no commentary.

RAW TRANSCRIPT:
{transcript}
"""


def cleanup_text(
    raw_lines: list[dict[str, Any]],
    language: str | None,
    metadata: dict[str, str] | None = None,
    cfg: LyricsConfig | None = None,
) -> dict[str, Any]:
    """Return ``{lines, raw_lines, cleaned: bool, error}``."""
    cfg = cfg or LyricsConfig.from_env()
    if not cfg.llm_cleanup_enabled:
        return {"lines": raw_lines, "raw_lines": raw_lines, "cleaned": False, "error": "disabled"}
    if LLM_FN is None:
        logger.info("llm cleanup enabled but no provider wired — keeping raw text")
        return {"lines": raw_lines, "raw_lines": raw_lines, "cleaned": False,
                "error": "no provider"}
    meta = ""
    if metadata:
        bits = [f"{k}: {v}" for k, v in metadata.items() if v]
        meta = f" ({', '.join(bits)})" if bits else ""
    prompt = CLEANUP_PROMPT.format(
        language=language or "unknown", meta=meta,
        transcript="\n".join(l.get("text", "") for l in raw_lines),
    )
    try:
        cleaned = LLM_FN(prompt, language=language, metadata=metadata or {})
        texts = [t for t in cleaned.splitlines() if t.strip()]
        if len(texts) != len(raw_lines):
            logger.warning("cleanup changed line count %d→%d — needs re-align",
                           len(raw_lines), len(texts))
        lines = [
            {"timestamp": raw_lines[i]["timestamp"] if i < len(raw_lines) else 0.0,
             "end": raw_lines[i]["end"] if i < len(raw_lines) else 0.0,
             "text": t.strip()}
            for i, t in enumerate(texts)
        ]
        return {"lines": lines or raw_lines, "raw_lines": raw_lines,
                "cleaned": True, "error": None,
                "realigned": len(texts) != len(raw_lines)}
    except Exception as exc:
        logger.warning("llm cleanup failed (%s) — keeping raw", exc)
        return {"lines": raw_lines, "raw_lines": raw_lines, "cleaned": False,
                "error": str(exc)[:300]}


def _ensure_urduhack_shim() -> None:
    """ai4bharat-transliteration imports `urduhack` (shahmukhi/Urdu normalizer)
    at module load, which drags in tensorflow — a ~600 MB dep for a code path
    hi/ml never touches. Pre-shim it with a passthrough when the real package
    is absent; full Urdu support = install urduhack + tensorflow."""
    import sys
    import types

    try:
        import urduhack  # noqa: F401
    except ModuleNotFoundError:
        import logging as _logging

        _logging.getLogger(__name__).info(
            "urduhack absent — shimming shahmukhi normalize (hi/ml unaffected)"
        )
        shim = types.ModuleType("urduhack")
        shim.normalize = lambda text: text  # type: ignore[attr-defined]
        sys.modules["urduhack"] = shim


def _get_xlit():
    global _xlit_engine
    if _xlit_engine is None:
        _ensure_urduhack_shim()
        from ai4bharat.transliteration import XlitEngine

        # Native → Roman direction (verified against package source).
        _xlit_engine = XlitEngine(src_script_type="indic", model_type="transformer")
    return _xlit_engine


def _roman_backend() -> str:
    import os

    return os.getenv("LYRICS_ROMAN_BACKEND", "indic").strip().lower()


def romanise_line(text: str, lang_code: str) -> str:
    """Native-script line → Roman. ``indic`` backend (sanscript HK) by default;
    ``xlit`` backend when configured and runnable. Cached per line."""
    from pipeline.cache import cache_path

    from pipeline.config import LyricsConfig as _C

    backend = _roman_backend()
    key = cache_path(_C.from_env().cache_dir, "roman", backend, lang_code, text,
                     ext=".txt")
    try:
        if key.exists():
            return key.read_text(encoding="utf-8")
    except OSError:
        pass
    if backend == "xlit":
        out = _get_xlit().translit_sentence(text, lang_code)
    else:
        from indic_transliteration import sanscript
        from indic_transliteration.sanscript import transliterate

        src = {"hi": sanscript.DEVANAGARI, "ml": sanscript.MALAYALAM}.get(lang_code)
        if src is None:
            return text
        out = transliterate(text, src, sanscript.HK)
    try:
        key.parent.mkdir(parents=True, exist_ok=True)
        key.write_text(out, encoding="utf-8")
    except OSError:
        pass
    return out


def romanise_lines(
    lines: list[dict[str, Any]], lang_code: str | None
) -> list[dict[str, Any]]:
    """Attach ``roman`` to each line; falls back to native text when the
    engine/lang is unavailable. Storage stays native-script."""
    if not lines or not lang_code or lang_code not in ("hi", "ml"):
        return lines
    if _roman_backend() == "xlit":
        try:
            _get_xlit()
        except ImportError:
            logger.info("indicxlit not installed — romanisation off")
            return lines
        except Exception as exc:
            logger.warning("romanisation engine failed (%s)", exc)
            return lines
    else:
        try:
            import indic_transliteration  # noqa: F401
        except ImportError:
            logger.info("indic-transliteration not installed — romanisation off")
            return lines
    out = []
    for line in lines:
        try:
            if _roman_backend() == "xlit":
                _get_xlit()  # raises when blocked → native fallback below
            roman = romanise_line(line.get("text", ""), lang_code)
        except ImportError:
            logger.info("romanisation backend unavailable — native only")
            return lines
        except Exception as exc:
            logger.debug("romanise failed (%s)", exc)
            roman = line.get("text", "")
        out.append({**line, "roman": roman})
    return out
