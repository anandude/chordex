"""
storage.py
----------
Upload storage abstraction for API ↔ worker file handoff.

Local mode (default): shared filesystem under UPLOAD_DIR.
S3 mode (optional): set S3_BUCKET (+ optional AWS creds / endpoint for R2).

Public API:
    save_upload(job_id, contents, ext) -> str   # returns storage URI
    resolve_path(uri) -> str                    # local path for worker
    get_bytes(uri) -> bytes                     # for audio streaming
    cleanup(uri) -> None
    uri_for_job(job_id) -> str | None           # lookup stored URI by job id
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

# Local shared volume (docker-compose mounts the same path on API + worker)
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/tmp/chordex_uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

_S3_BUCKET = os.getenv("S3_BUCKET", "").strip()
_S3_PREFIX = os.getenv("S3_PREFIX", "uploads").strip().strip("/")
_S3_ENDPOINT = os.getenv("S3_ENDPOINT_URL", "").strip() or None
_S3_REGION = os.getenv("AWS_REGION", "auto")


def _s3_enabled() -> bool:
    return bool(_S3_BUCKET)


def _s3_client():
    import boto3

    kwargs: dict = {"region_name": _S3_REGION}
    if _S3_ENDPOINT:
        kwargs["endpoint_url"] = _S3_ENDPOINT
    return boto3.client("s3", **kwargs)


def _s3_key(job_id: str, ext: str) -> str:
    return f"{_S3_PREFIX}/{job_id}/audio.{ext}"


def save_upload(job_id: str, contents: bytes, ext: str) -> str:
    """
    Persist uploaded audio. Returns a URI:
      file://{UPLOAD_DIR}/{job_id}/audio.{ext}
      s3://{bucket}/{prefix}/{job_id}/audio.{ext}
    """
    ext = ext.lstrip(".").lower()
    if _s3_enabled():
        key = _s3_key(job_id, ext)
        client = _s3_client()
        client.put_object(Bucket=_S3_BUCKET, Key=key, Body=contents)
        return f"s3://{_S3_BUCKET}/{key}"

    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    path = job_dir / f"audio.{ext}"
    path.write_bytes(contents)
    # Also write a tiny marker so we can find URI by job_id
    (job_dir / "meta.txt").write_text(f"ext={ext}\n", encoding="utf-8")
    return f"file://{path}"


def resolve_path(uri: str) -> str:
    """
    Return a local filesystem path for analysis.
    For s3:// URIs, downloads into a temp path under UPLOAD_DIR.
    """
    if uri.startswith("file://"):
        return uri[len("file://") :]

    if uri.startswith("s3://"):
        # s3://bucket/key...
        without = uri[len("s3://") :]
        bucket, _, key = without.partition("/")
        local_dir = UPLOAD_DIR / "s3_cache" / Path(key).parent.name
        local_dir.mkdir(parents=True, exist_ok=True)
        local_path = local_dir / Path(key).name
        if not local_path.exists():
            client = _s3_client()
            client.download_file(bucket, key, str(local_path))
        return str(local_path)

    # Bare path fallback
    return uri


def get_bytes(uri: str) -> bytes:
    path = resolve_path(uri)
    return Path(path).read_bytes()


def get_content_type(uri: str) -> str:
    path = resolve_path(uri)
    ext = Path(path).suffix.lstrip(".").lower()
    return {
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "ogg": "audio/ogg",
        "flac": "audio/flac",
        "m4a": "audio/mp4",
    }.get(ext, "application/octet-stream")


def uri_for_job(job_id: str) -> str | None:
    """Best-effort locate a previously saved upload for this job."""
    if _s3_enabled():
        # Probe common extensions
        client = _s3_client()
        for ext in ("mp3", "wav", "ogg", "flac", "m4a"):
            key = _s3_key(job_id, ext)
            try:
                client.head_object(Bucket=_S3_BUCKET, Key=key)
                return f"s3://{_S3_BUCKET}/{key}"
            except Exception:
                continue
        return None

    job_dir = UPLOAD_DIR / job_id
    if not job_dir.is_dir():
        return None
    for p in job_dir.glob("audio.*"):
        return f"file://{p}"
    return None


def cleanup(uri: str) -> None:
    """Best-effort delete of stored audio (and parent job dir if empty)."""
    try:
        if uri.startswith("file://"):
            path = Path(uri[len("file://") :])
            if path.is_file():
                path.unlink()
            parent = path.parent
            if parent.is_dir() and parent != UPLOAD_DIR:
                for leftover in parent.iterdir():
                    leftover.unlink(missing_ok=True)
                parent.rmdir()
            return

        if uri.startswith("s3://") and _s3_enabled():
            without = uri[len("s3://") :]
            bucket, _, key = without.partition("/")
            _s3_client().delete_object(Bucket=bucket, Key=key)
            # local cache
            cache = UPLOAD_DIR / "s3_cache" / Path(key).parent.name
            if cache.is_dir():
                shutil.rmtree(cache, ignore_errors=True)
    except Exception:
        pass
