"""
Chord recognition engines.

Select via CHORD_ENGINE env:
  auto      — Chordino if available, else improved template (default)
  chordino  — Chordino / NNLS-chroma only
  template  — improved template + HMM only
"""

from __future__ import annotations

import os

from chord_engine.base import AnalysisResult, ChordEngine
from chord_engine.template_engine import TemplateChordEngine


def get_engine(name: str | None = None) -> ChordEngine:
    choice = (name or os.getenv("CHORD_ENGINE", "auto")).strip().lower()

    if choice in ("chordino", "auto"):
        try:
            from chord_engine.chordino_engine import ChordinoEngine

            engine = ChordinoEngine()
            if engine.available():
                return engine
            if choice == "chordino":
                raise RuntimeError(
                    "CHORD_ENGINE=chordino but Chordino/vamp is not available. "
                    "Install chord-extractor and ensure the Vamp plugin binary works."
                )
        except ImportError:
            if choice == "chordino":
                raise
            # fall through to template

    return TemplateChordEngine()


__all__ = ["AnalysisResult", "ChordEngine", "get_engine", "TemplateChordEngine"]
