"""
chord_detector.py
-----------------
Public entry point for chord analysis.

Delegates to chord_engine (Chordino when available, else improved template+HMM).
Kept as a stable import path for the RQ worker.
"""

from __future__ import annotations

import logging
import os

from chord_engine import get_engine

logger = logging.getLogger(__name__)


def _chord_source() -> str:
    """A4.1: chord input — "mix" (default) or "stem" (demucs accompaniment).

    "stem" isolates drums+bass+other before analysis, helping dense/distorted
    mixes at the cost of a demucs run. Any other value warns and uses "mix".
    """
    source = os.getenv("CHORD_SOURCE", "mix").strip().lower()
    if source not in {"mix", "stem"}:
        logger.warning("Unknown CHORD_SOURCE=%r, using 'mix'", source)
        return "mix"
    return source


def detect_chords(file_path: str, engine: str | None = None) -> dict:
    """
    Analyse an audio file and return timestamped chords plus metadata.

    Returns
    -------
    dict with keys:
        chords   : list of {timestamp, end, chord, confidence}
        tempo    : float BPM
        key      : str e.g. "G major"
        duration : float seconds
        engine   : str engine name used ("+stem" suffix when CHORD_SOURCE=stem,
                   so eval rows stay comparable)
    """
    analysis_path = file_path
    stemmed = False
    if _chord_source() == "stem":
        try:
            from pipeline.separation import separate_accompaniment

            stem_path = separate_accompaniment(file_path)
            # separate_accompaniment falls back to the input on any problem;
            # only tag when we genuinely got a different file.
            if str(stem_path) != str(file_path):
                analysis_path = str(stem_path)
                stemmed = True
        except Exception as exc:
            logger.warning("accompaniment stem failed (%s) — using mixture", exc)
    result = get_engine(engine).analyze(analysis_path)
    if stemmed:
        result["engine"] = f"{result.get('engine', 'unknown')}+stem"
    return result
