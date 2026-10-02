"""
Chordino engine — wraps the industry-standard NNLS-Chroma Chordino plugin
via the `chord-extractor` package (includes Linux x64 Vamp binary).

MIREX-class accuracy (~67–77% maj/min on Billboard); large chord vocabulary
including 7ths and altered chords.
"""

from __future__ import annotations

import logging
import os

import librosa
import numpy as np

from label_map import normalize_chord
from postprocess import build_light_result, build_result

logger = logging.getLogger(__name__)


def _meta_enabled() -> bool:
    """CHORD_META=0 skips the full-decode post-processing (key/tempo/beats).

    The vamp plugin decodes the file internally regardless; this flag avoids
    the *second* full decode in this method plus key/tempo/beat analysis.
    Duration then comes from a metadata-only probe (milliseconds, not
    seconds). Default on — behavior unchanged unless opted out.
    """
    return os.getenv("CHORD_META", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


class ChordinoEngine:
    name = "chordino"

    def __init__(self) -> None:
        self._chordino = None
        self._import_error: str | None = None
        try:
            from chord_extractor.extractors import Chordino

            # roll_on helps suppress spurious early detections
            self._chordino = Chordino(roll_on=1)
        except Exception as exc:  # ImportError or plugin load failure
            self._import_error = str(exc)
            logger.warning("Chordino unavailable: %s", exc)

    def available(self) -> bool:
        return self._chordino is not None

    def analyze(self, file_path: str) -> dict:
        if self._chordino is None:
            raise RuntimeError(
                f"Chordino engine not available: {self._import_error}"
            )

        # chord-extractor / vamp expects a path librosa can load
        changes = self._chordino.extract(file_path)

        # S2 note: snap_to_beats=None resolves via the SNAP_TO_BEATS env
        # (default on). The beat_track call below is shared between tempo
        # estimation and beat-snapping inside build_result.
        if not _meta_enabled():
            # S1 fast path: no second decode, no key/tempo/beat analysis.
            # Duration is probed from container metadata (no waveform decode).
            try:
                duration = float(librosa.get_duration(path=file_path))
            except Exception:
                duration = 0.0
            raw_events: list[dict] = []
            for i, ch in enumerate(changes):
                chord = normalize_chord(getattr(ch, "chord", str(ch)))
                ts = float(getattr(ch, "timestamp", 0.0))
                if i + 1 < len(changes):
                    end = float(getattr(changes[i + 1], "timestamp", ts + 1.0))
                else:
                    end = duration
                raw_events.append(
                    {
                        "timestamp": ts,
                        "end": end,
                        "chord": chord,
                        "confidence": 0.85 if chord != "N" else 0.5,
                    }
                )
            return build_light_result(
                raw_events,
                duration=duration,
                engine=self.name,
                min_duration=0.4,
            )

        y, sr = librosa.load(file_path, sr=22050, mono=True)
        duration = float(len(y) / sr)

        raw_events: list[dict] = []
        for i, ch in enumerate(changes):
            # ChordChange(chord=str, timestamp=float)
            chord = normalize_chord(getattr(ch, "chord", str(ch)))
            ts = float(getattr(ch, "timestamp", 0.0))
            if i + 1 < len(changes):
                end = float(getattr(changes[i + 1], "timestamp", ts + 1.0))
            else:
                end = duration
            raw_events.append(
                {
                    "timestamp": ts,
                    "end": end,
                    "chord": chord,
                    "confidence": 0.85 if chord != "N" else 0.5,
                }
            )

        return build_result(
            raw_events,
            y=y,
            sr=sr,
            engine=self.name,
            min_duration=0.4,
            snap_to_beats=None,
        )
