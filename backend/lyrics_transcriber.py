"""
lyrics_transcriber.py
---------------------
Word-level lyrics via faster-whisper.

Env:
  ENABLE_LYRICS=1|0     default 1
  WHISPER_MODEL=tiny|base|small|medium|large-v3   default tiny (CPU-friendly)
  WHISPER_DEVICE=cpu|cuda  default cpu
  WHISPER_COMPUTE_TYPE=int8|float16|float32  default int8 on cpu
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_model = None
_model_name: str | None = None


def lyrics_enabled() -> bool:
    return os.getenv("ENABLE_LYRICS", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _get_model():
    global _model, _model_name
    name = os.getenv("WHISPER_MODEL", "tiny").strip()
    if _model is not None and _model_name == name:
        return _model

    from faster_whisper import WhisperModel

    device = os.getenv("WHISPER_DEVICE", "cpu").strip()
    compute = os.getenv(
        "WHISPER_COMPUTE_TYPE",
        "int8" if device == "cpu" else "float16",
    ).strip()

    logger.info("Loading Whisper model=%s device=%s compute=%s", name, device, compute)
    _model = WhisperModel(name, device=device, compute_type=compute)
    _model_name = name
    return _model


def transcribe_lyrics(file_path: str) -> dict[str, Any]:
    """
    Returns:
      {
        "lyrics": [{"timestamp": float, "end": float, "word": str}, ...],
        "lines":  [{"timestamp": float, "end": float, "text": str}, ...],
        "language": str | None,
        "error": str | None,
      }
    """
    if not lyrics_enabled():
        return {
            "lyrics": [],
            "lines": [],
            "language": None,
            "error": "lyrics disabled (ENABLE_LYRICS=0)",
        }

    try:
        model = _get_model()
        segments, info = model.transcribe(
            file_path,
            word_timestamps=True,
            vad_filter=True,
            beam_size=1,
        )

        words: list[dict[str, Any]] = []
        lines: list[dict[str, Any]] = []

        for seg in segments:
            text = (seg.text or "").strip()
            if text:
                lines.append(
                    {
                        "timestamp": round(float(seg.start or 0.0), 3),
                        "end": round(float(seg.end or 0.0), 3),
                        "text": text,
                    }
                )
            if seg.words:
                for w in seg.words:
                    token = (w.word or "").strip()
                    if not token:
                        continue
                    words.append(
                        {
                            "timestamp": round(float(w.start or 0.0), 3),
                            "end": round(float(w.end or 0.0), 3),
                            "word": token,
                        }
                    )

        lang = getattr(info, "language", None)
        return {
            "lyrics": words,
            "lines": lines,
            "language": lang,
            "error": None,
        }
    except Exception as exc:
        logger.exception("Lyrics transcription failed")
        return {
            "lyrics": [],
            "lines": [],
            "language": None,
            "error": str(exc)[:500],
        }
