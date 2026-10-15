"""
pipeline/gpu.py
---------------
Device resolution for the lyrics models.

Two runtimes, two device stories:

* torch (demucs, MMS aligner, transformers ASR) — ``LyricsConfig.torch_device``.
* CTranslate2 (faster-whisper) — needs the **CUDA 12** cuBLAS libraries
  (``libcublas.so.12``), while the venv's torch wheel ships CUDA 13. The
  ``nvidia-cublas-cu12`` wheel provides them; we preload it in-process with
  RTLD_GLOBAL so CTranslate2's later ``dlopen("libcublas.so.12")`` resolves
  without LD_LIBRARY_PATH. If anything is missing, Whisper runs on CPU int8.
"""

from __future__ import annotations

import ctypes
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_cuda12_ok: bool | None = None


def preload_cuda12() -> bool:
    """Load cuBLAS 12 from the nvidia-cublas-cu12 wheel. Idempotent."""
    global _cuda12_ok
    if _cuda12_ok is not None:
        return _cuda12_ok
    _cuda12_ok = False
    try:
        import nvidia.cublas  # namespace package from nvidia-cublas-cu12

        libdir = Path(list(nvidia.cublas.__path__)[0]) / "lib"
        for name in ("libcublasLt.so.12", "libcublas.so.12"):
            ctypes.CDLL(str(libdir / name), mode=ctypes.RTLD_GLOBAL)
        _cuda12_ok = True
    except Exception as exc:
        # The system may still provide CUDA 12 libs on the loader path.
        try:
            ctypes.CDLL("libcublas.so.12", mode=ctypes.RTLD_GLOBAL)
            _cuda12_ok = True
        except OSError:
            logger.info("cuBLAS 12 unavailable (%s) — Whisper will run on CPU", exc)
    return _cuda12_ok


def whisper_device(preference: str) -> str:
    """Resolve WHISPER_DEVICE: auto → cuda when CTranslate2 sees a GPU and the
    CUDA 12 libraries load, else cpu. Explicit cuda degrades the same way."""
    pref = (preference or "auto").lower()
    if pref == "cpu":
        return "cpu"
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0 and preload_cuda12():
            return "cuda"
    except Exception:
        pass
    if pref.startswith("cuda"):
        logger.warning("WHISPER_DEVICE=%s requested but CUDA is unusable — cpu", pref)
    return "cpu"


def whisper_compute_type(device: str, configured: str) -> str:
    """int8_float16 on CUDA: on the GTX 1650 (no tensor cores) float16 was 3x
    slower than int8_float16/float32 (11.6 s vs 3.8 s, Whisper small, 3-min
    song, identical output), and int8 weights leave VRAM headroom for the
    medium Indic models next to the aligner. Override with
    WHISPER_COMPUTE_TYPE=float16 on tensor-core GPUs."""
    if configured:
        return configured
    return "int8_float16" if device == "cuda" else "int8"
