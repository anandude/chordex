"""
postprocess.py
--------------
Shared post-processing for chord timelines produced by any engine.

- Merge consecutive identical labels
- Drop / absorb very short segments
- Optional beat-snap of boundaries
- Attach end times + confidence
- Key estimation from chroma (librosa)
"""

from __future__ import annotations

from typing import Any

import librosa
import numpy as np

from label_map import normalize_chord

NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Krumhansl–Schmuckler profiles for *key* estimation (correct use-case)
_MAJOR_PROFILE = np.array(
    [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
)
_MINOR_PROFILE = np.array(
    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
)


def estimate_key(y: np.ndarray, sr: int) -> str:
    """Return e.g. 'G major' or 'A minor' from global chroma correlation."""
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    chroma_mean = chroma.mean(axis=1)
    if np.linalg.norm(chroma_mean) < 1e-8:
        return "unknown"

    best_score = -np.inf
    best_label = "unknown"
    for i, note in enumerate(NOTES):
        maj = np.corrcoef(chroma_mean, np.roll(_MAJOR_PROFILE, i))[0, 1]
        mi = np.corrcoef(chroma_mean, np.roll(_MINOR_PROFILE, i))[0, 1]
        if maj > best_score:
            best_score = maj
            best_label = f"{note} major"
        if mi > best_score:
            best_score = mi
            best_label = f"{note} minor"
    return best_label


def estimate_tempo(y: np.ndarray, sr: int) -> float:
    tempo_result, _ = librosa.beat.beat_track(y=y, sr=sr)
    return round(float(np.atleast_1d(tempo_result)[0]), 1)


def get_beat_times(y: np.ndarray, sr: int) -> np.ndarray:
    _, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
    return np.asarray(beats, dtype=float)


def _snap_time(t: float, beats: np.ndarray, max_snap: float = 0.35) -> float:
    if beats.size == 0:
        return t
    idx = int(np.argmin(np.abs(beats - t)))
    if abs(beats[idx] - t) <= max_snap:
        return float(beats[idx])
    return t


def merge_segments(
    events: list[dict[str, Any]],
    *,
    min_duration: float = 0.45,
    total_duration: float | None = None,
) -> list[dict[str, Any]]:
    """
    Normalize labels, merge consecutive same chords, drop short blips
    by absorbing into neighbors, ensure end times.
    """
    if not events:
        return []

    # Normalize + sort
    cleaned: list[dict[str, Any]] = []
    for e in events:
        chord = normalize_chord(e.get("chord", "N"))
        ts = float(e["timestamp"])
        conf = float(e.get("confidence", 1.0))
        cleaned.append({"timestamp": ts, "chord": chord, "confidence": conf})
    cleaned.sort(key=lambda x: x["timestamp"])

    # Merge consecutive identical
    merged: list[dict[str, Any]] = []
    for e in cleaned:
        if merged and merged[-1]["chord"] == e["chord"]:
            # keep earlier start; average confidence
            n = merged[-1].get("_n", 1)
            merged[-1]["confidence"] = (
                merged[-1]["confidence"] * n + e["confidence"]
            ) / (n + 1)
            merged[-1]["_n"] = n + 1
        else:
            e = {**e, "_n": 1}
            merged.append(e)

    # Assign provisional ends
    for i, e in enumerate(merged):
        if i + 1 < len(merged):
            e["end"] = merged[i + 1]["timestamp"]
        else:
            e["end"] = (
                float(total_duration)
                if total_duration is not None
                else e["timestamp"] + 2.0
            )

    # Absorb short segments into the longer neighbor
    i = 0
    while i < len(merged):
        e = merged[i]
        dur = e["end"] - e["timestamp"]
        if dur < min_duration and len(merged) > 1:
            if i == 0:
                # absorb into next
                merged[i + 1]["timestamp"] = e["timestamp"]
                merged.pop(i)
                continue
            elif i == len(merged) - 1:
                merged[i - 1]["end"] = e["end"]
                merged.pop(i)
                continue
            else:
                # absorb into longer neighbor
                prev_dur = merged[i - 1]["end"] - merged[i - 1]["timestamp"]
                next_dur = merged[i + 1]["end"] - merged[i + 1]["timestamp"]
                if prev_dur >= next_dur:
                    merged[i - 1]["end"] = e["end"]
                else:
                    merged[i + 1]["timestamp"] = e["timestamp"]
                merged.pop(i)
                continue
        i += 1

    # Re-merge if neighbors became identical after absorption
    final: list[dict[str, Any]] = []
    for e in merged:
        if final and final[-1]["chord"] == e["chord"]:
            final[-1]["end"] = e["end"]
            final[-1]["confidence"] = (final[-1]["confidence"] + e["confidence"]) / 2
        else:
            final.append(
                {
                    "timestamp": round(float(e["timestamp"]), 3),
                    "end": round(float(e["end"]), 3),
                    "chord": e["chord"],
                    "confidence": round(float(e["confidence"]), 3),
                }
            )
    return final


def beat_snap_events(
    events: list[dict[str, Any]],
    beats: np.ndarray,
    *,
    max_snap: float = 0.35,
) -> list[dict[str, Any]]:
    if not events or beats.size == 0:
        return events
    snapped = []
    for e in events:
        ts = _snap_time(e["timestamp"], beats, max_snap=max_snap)
        end = _snap_time(e["end"], beats, max_snap=max_snap)
        if end <= ts:
            end = e["end"]
        snapped.append({**e, "timestamp": round(ts, 3), "end": round(end, 3)})
    # re-merge after snap
    return merge_segments(snapped, min_duration=0.3)


def build_result(
    raw_events: list[dict[str, Any]],
    *,
    y: np.ndarray,
    sr: int,
    engine: str,
    min_duration: float = 0.45,
    snap_to_beats: bool = True,
) -> dict[str, Any]:
    duration = float(len(y) / sr) if len(y) else 0.0
    events = merge_segments(
        raw_events, min_duration=min_duration, total_duration=duration
    )

    tempo = estimate_tempo(y, sr)
    key = estimate_key(y, sr)

    if snap_to_beats and events:
        try:
            beats = get_beat_times(y, sr)
            events = beat_snap_events(events, beats)
            # re-apply duration ends
            for i, e in enumerate(events):
                if i + 1 < len(events):
                    e["end"] = events[i + 1]["timestamp"]
                else:
                    e["end"] = round(duration, 3)
        except Exception:
            pass

    return {
        "chords": events,
        "tempo": tempo,
        "key": key,
        "duration": round(duration, 3),
        "engine": engine,
    }
