"""
pipeline/hf_setup.py
--------------------
Hugging Face Hub process-level setup and cache introspection. Import this
*before* any pipeline stage touches ``huggingface_hub`` (``asr.py``,
``worker.py`` and ``prewarm.py`` all do).

Why: ``hf-xet`` (the Xet transfer backend) silently stalls on some networks.
Measured on this machine, same file, same 40 s window:

    default (hf-xet 1.5.2)        17,361 bytes written
    HF_HUB_DISABLE_XET=1      20,971,520 bytes written  (~525 KB/s)

A stalled download never fails — it just sits there writing a couple of KB,
which is what made a first-time ASR run look like a hung job. Disabling Xet
falls back to the plain CDN (and to resumable ``.incomplete`` blobs), which
works. Set ``HF_HUB_DISABLE_XET=0`` in the environment to try Xet again after
upgrading ``hf-xet``.
"""

from __future__ import annotations

import fnmatch
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

#: Files that mean "this repo's weights are on disk".
WEIGHT_PATTERNS = ("*.safetensors", "*.bin", "*.ckpt", "*.pt", "*.gguf")

#: Recognised spellings of "on" for HF_HUB_DISABLE_XET.
_FALSEY = {"0", "false", "no", "off"}


def disable_xet() -> bool:
    """Route HF downloads through the plain CDN instead of Xet.

    Idempotent, and respects an explicit opt-in (``HF_HUB_DISABLE_XET=0``).
    Returns True when Xet is disabled for this process.
    """
    raw = os.getenv("HF_HUB_DISABLE_XET")
    if raw is not None and raw.strip().lower() in _FALSEY:
        logger.info("hf_setup: xet backend explicitly enabled (HF_HUB_DISABLE_XET=0)")
        return False
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    return True


XET_DISABLED = disable_xet()


def hf_cache_dir() -> Path:
    """Local HF hub cache (``HF_HOME``/``HF_HUB_CACHE`` aware)."""
    try:
        from huggingface_hub import constants

        return Path(constants.HF_HUB_CACHE)
    except Exception:  # pragma: no cover - huggingface_hub always present here
        home = os.getenv("HF_HOME") or str(Path.home() / ".cache" / "huggingface")
        return Path(home) / "hub"


def repo_cache_dir(repo_id: str) -> Path:
    return hf_cache_dir() / ("models--" + repo_id.replace("/", "--"))


def repo_cache_state(repo_id: str) -> tuple[bool, float]:
    """``(fully_cached, bytes_on_disk)`` for a Hub repo.

    Deliberately filesystem-based: ``snapshot_download(local_files_only=True)``
    returns happily for a repo where only ``config.json`` was fetched, which is
    exactly the state a killed download leaves behind. A complete download means
    a weights file is tracked in a snapshot *and* no ``*.incomplete`` blob is
    still lying around (``huggingface_hub`` only links the snapshot entry once
    the blob is finished, so this catches half-written weights).
    """
    repo_dir = repo_cache_dir(repo_id)
    if not repo_dir.is_dir():
        return False, 0.0

    total = 0.0
    for blob in (repo_dir / "blobs").glob("*"):
        try:
            if blob.is_file():
                total += blob.stat().st_size
        except OSError:
            pass

    if any((repo_dir / "blobs").glob("*.incomplete")):
        return False, total

    has_weights = False
    for snapshot in (repo_dir / "snapshots").glob("*"):
        for entry in snapshot.rglob("*"):
            if entry.is_file() and any(
                fnmatch.fnmatch(entry.name, pat) for pat in WEIGHT_PATTERNS
            ):
                has_weights = True
                break
        if has_weights:
            break
    return has_weights, total