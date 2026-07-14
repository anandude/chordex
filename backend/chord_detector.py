"""
chord_detector.py
-----------------
Public entry point for chord analysis.

Delegates to chord_engine (Chordino when available, else improved template+HMM).
Kept as a stable import path for the RQ worker.
"""

from __future__ import annotations

from chord_engine import get_engine


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
        engine   : str engine name used
    """
    return get_engine(engine).analyze(file_path)
