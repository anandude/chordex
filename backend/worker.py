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

    1. Chord recognition
    2. Easy-mode suggestion (pure theory, from chords)
    3. Optional lyrics transcription (faster-whisper)
    """
    from chord_detector import detect_chords
    from easy_chords import apply_easy_mode
    from lyrics_transcriber import lyrics_enabled, transcribe_lyrics

    # Derive job_id
    if audio_uri.startswith("file://"):
        path = Path(audio_uri[len("file://") :])
        job_id = path.parent.name
    elif audio_uri.startswith("s3://"):
        key = audio_uri.split("s3://", 1)[1].split("/", 1)[1]
        job_id = Path(key).parent.name
    else:
        job_id = Path(audio_uri).parent.name

    local_path = storage.resolve_path(audio_uri)
    result = detect_chords(local_path)

    # Easy mode metadata (client can recompute; we precompute for convenience)
    try:
        easy = apply_easy_mode(result.get("chords", []), key=result.get("key"))
        result["easy"] = {
            "capo": easy["capo"],
            "score": easy["score"],
            "easy_key": easy.get("easy_key"),
            "reason": easy["reason"],
            "chords": easy["chords"],
        }
    except Exception as exc:
        result["easy"] = {
            "capo": 0,
            "score": 0.0,
            "easy_key": result.get("key"),
            "reason": f"Easy mode unavailable: {exc}",
            "chords": result.get("chords", []),
        }

    # Lyrics (best-effort — never fail the whole job)
    if lyrics_enabled():
        lyrics_out = transcribe_lyrics(local_path)
        result["lyrics"] = lyrics_out.get("lyrics", [])
        result["lyric_lines"] = lyrics_out.get("lines", [])
        result["lyrics_language"] = lyrics_out.get("language")
        if lyrics_out.get("error"):
            result["lyrics_error"] = lyrics_out["error"]
    else:
        result["lyrics"] = []
        result["lyric_lines"] = []
        result["lyrics_error"] = "disabled"

    redis_conn = redis.from_url(REDIS_URL, decode_responses=True)
    redis_conn.setex(f"result:{job_id}", _RESULT_TTL, json.dumps(result))
    redis_conn.setex(f"uri:{job_id}", _RESULT_TTL, audio_uri)

    return result


if __name__ == "__main__":
    redis_conn = redis.from_url(REDIS_URL)
    q = Queue("chord_jobs", connection=redis_conn)
    worker = Worker([q], connection=redis_conn)
    print("Worker started. Listening on queue: chord_jobs")
    print(f"UPLOAD_DIR={storage.UPLOAD_DIR}")
    print(f"CHORD_ENGINE={os.getenv('CHORD_ENGINE', 'auto')}")
    print(f"ENABLE_LYRICS={os.getenv('ENABLE_LYRICS', '1')}")
    print(f"WHISPER_MODEL={os.getenv('WHISPER_MODEL', 'tiny')}")
    worker.work()
