"""
worker.py
---------
RQ worker entry point and job function.

Run this as a separate process:
    python worker.py
"""

import json
import os
from pathlib import Path

import redis
from dotenv import load_dotenv
from rq import Queue, Worker

import storage

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
_RESULT_TTL = 3600


def run_chord_detection(audio_uri: str) -> dict:
    """
    RQ job payload.

    Parameters
    ----------
    audio_uri : str
        Storage URI from storage.save_upload (file://… or s3://…).
        For backward compatibility, a bare filesystem path is also accepted.
    """
    from chord_detector import detect_chords

    # Derive job_id
    if audio_uri.startswith("file://"):
        path = Path(audio_uri[len("file://") :])
        job_id = path.parent.name
    elif audio_uri.startswith("s3://"):
        # s3://bucket/prefix/{job_id}/audio.ext
        key = audio_uri.split("s3://", 1)[1].split("/", 1)[1]
        job_id = Path(key).parent.name
    else:
        # legacy bare path: /tmp/{job_id}/audio.ext
        job_id = Path(audio_uri).parent.name

    local_path = storage.resolve_path(audio_uri)
    result = detect_chords(local_path)

    redis_conn = redis.from_url(REDIS_URL, decode_responses=True)
    redis_conn.setex(f"result:{job_id}", _RESULT_TTL, json.dumps(result))
    # Keep URI around for playback for the same window
    redis_conn.setex(f"uri:{job_id}", _RESULT_TTL, audio_uri)

    # Do NOT delete audio immediately — frontend needs it for playback.
    # Cleanup is deferred: files older than RESULT_TTL can be swept later.
    # For s3_cache local copies of s3 objects we leave them; TTL on redis is source of truth.

    return result


if __name__ == "__main__":
    redis_conn = redis.from_url(REDIS_URL)
    q = Queue("chord_jobs", connection=redis_conn)
    worker = Worker([q], connection=redis_conn)
    print("Worker started. Listening on queue: chord_jobs")
    print(f"UPLOAD_DIR={storage.UPLOAD_DIR}")
    print(f"CHORD_ENGINE={os.getenv('CHORD_ENGINE', 'auto')}")
    worker.work()
