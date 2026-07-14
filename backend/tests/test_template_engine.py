"""Smoke test: synthetic C major triad should detect C-family chord."""

import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chord_engine.template_engine import TemplateChordEngine


def _write_c_major_wav(path: Path, duration: float = 3.0, sr: int = 22050) -> None:
    """Generate a simple C major triad (C4 E4 G4) as 16-bit mono WAV."""
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    # frequencies for C4, E4, G4
    freqs = [261.63, 329.63, 392.00]
    y = sum(0.3 * np.sin(2 * np.pi * f * t) for f in freqs)
    # mild envelope
    env = np.minimum(1.0, np.linspace(0, 20, len(y)))
    env = env * np.minimum(1.0, np.linspace(20, 0, len(y)))
    y = (y * env * 0.8).astype(np.float32)
    pcm = np.clip(y * 32767, -32768, 32767).astype(np.int16)

    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def test_detects_c_major(tmp_path):
    wav = tmp_path / "c_major.wav"
    _write_c_major_wav(wav, duration=4.0)

    engine = TemplateChordEngine()
    result = engine.analyze(str(wav))

    assert "chords" in result
    assert result["tempo"] > 0 or result["tempo"] == 0.0
    assert result["engine"] == "template-hmm"
    assert result["duration"] > 3.0

    labels = [c["chord"] for c in result["chords"] if c["chord"] != "N"]
    assert labels, "expected at least one non-N chord"
    # Root should be C for pure C major (allow C7/Cmaj7 etc.)
    assert any(lab.startswith("C") and not lab.startswith("C#") for lab in labels), (
        f"expected C-family chord, got {labels}"
    )
