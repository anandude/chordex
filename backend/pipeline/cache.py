"""
pipeline/cache.py
-----------------
Content-hash-keyed on-disk cache. One helper, every stage uses it:
separated stems, LRCLIB responses, ASR output, alignments, romanisations.
A re-upload of the same file is near-instant.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any


def content_hash(path: str | Path, *, chunk_mb: int = 4) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_mb * 1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()[:32]


def cache_path(cache_dir: str | Path, *parts: str, ext: str = ".json") -> Path:
    key = hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]
    d = Path(cache_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}{ext}"


def stage_cache_path(
    cache_dir: str | Path, stage: str, audio_path: str | Path, *extra: str,
    ext: str = ".json",
) -> Path:
    """Key = sha256(source bytes) + stage + extra (backend/model version...)."""
    digest = content_hash(audio_path)
    return cache_path(cache_dir, stage, digest, *extra, ext=ext)


def read_json(path: Path, *, max_age_s: int = 0) -> Any | None:
    try:
        if not path.exists():
            return None
        if max_age_s > 0 and (time.time() - path.stat().st_mtime) > max_age_s:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_json(path: Path, payload: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass
