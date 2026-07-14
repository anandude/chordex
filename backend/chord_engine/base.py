"""Shared types for chord engines."""

from __future__ import annotations

from typing import Any, Protocol, TypedDict


class ChordEvent(TypedDict, total=False):
    timestamp: float
    end: float
    chord: str
    confidence: float


class AnalysisResult(TypedDict, total=False):
    chords: list[dict[str, Any]]
    tempo: float
    key: str
    duration: float
    engine: str


class ChordEngine(Protocol):
    name: str

    def analyze(self, file_path: str) -> AnalysisResult:
        """Analyse audio file and return enriched chord result."""
        ...
