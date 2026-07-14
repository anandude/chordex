#!/usr/bin/env python3
"""Generate short synthetic audio fixtures for local testing."""

from pathlib import Path

import numpy as np
import wave

OUT = Path(__file__).resolve().parent
SR = 22050


def write_wav(path: Path, y: np.ndarray, sr: int = SR) -> None:
    pcm = np.clip(y * 32767, -32768, 32767).astype(np.int16)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def chord_tone(freqs: list[float], duration: float, sr: int = SR) -> np.ndarray:
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    y = sum(0.28 * np.sin(2 * np.pi * f * t) for f in freqs)
    # attack / release
    n = len(y)
    attack = min(int(0.02 * sr), n // 4)
    release = min(int(0.05 * sr), n // 4)
    env = np.ones(n)
    env[:attack] = np.linspace(0, 1, attack)
    env[-release:] = np.linspace(1, 0, release)
    return (y * env).astype(np.float32)


def main() -> None:
    # C major (C4 E4 G4) — 4 seconds
    c_maj = chord_tone([261.63, 329.63, 392.00], 4.0)
    write_wav(OUT / "c_major.wav", c_maj)

    # Simple I–IV–V–I in C: C | F | G | C  (2s each)
    c = chord_tone([261.63, 329.63, 392.00], 2.0)
    f = chord_tone([349.23, 440.00, 523.25], 2.0)  # F4 A4 C5
    g = chord_tone([392.00, 493.88, 587.33], 2.0)  # G4 B4 D5
    progression = np.concatenate([c, f, g, c])
    write_wav(OUT / "c_f_g_c.wav", progression)

    print(f"Wrote fixtures to {OUT}")


if __name__ == "__main__":
    main()
