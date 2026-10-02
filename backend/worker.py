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
from typing import Any

import redis
from dotenv import load_dotenv
from rq import Queue, Worker

import storage

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
_RESULT_TTL = 3600


def _publish_progress(redis_conn: Any, job_id: str, stage: str, pct: float) -> None:
    """Cross-cutting observability: UI polls stage-level progress."""
    try:
        redis_conn.setex(
            f"progress:{job_id}", 900, json.dumps({"stage": stage, "pct": pct})
        )
    except Exception:
        pass


def run_chord_detection(
    audio_uri: str,
    language: str | None = None,
    title: str | None = None,
    artist: str | None = None,
    album: str | None = None,
) -> dict:
    """
    RQ job payload.

    1. Chord recognition (untouched path)
    2. Easy-mode suggestion (pure theory, from chords)
    3. Lyrics chain: separate → lookup/ASR → align → clean (Phase 1→5)
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

    import time as _time

    local_path = storage.resolve_path(audio_uri)
    redis_conn = redis.from_url(REDIS_URL, decode_responses=True)
    _job_t0 = _time.time()
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
        _publish_progress(redis_conn, job_id, "separating", 0.15)

        def _on_stage(stage: str, pct: float) -> None:
            _publish_progress(redis_conn, job_id, stage, pct)

        lyrics_out = transcribe_lyrics(
            local_path, language=language, title=title, artist=artist,
            album=album, duration=result.get("duration"), progress=_on_stage,
        )
        result["lyrics"] = lyrics_out.get("lyrics", [])
        result["lyric_lines"] = lyrics_out.get("lines", [])
        result["lyrics_language"] = lyrics_out.get("language")
        result["lyrics_source"] = lyrics_out.get("source", "asr")
        if lyrics_out.get("stages"):
            result["lyrics_stages"] = lyrics_out["stages"]
        if lyrics_out.get("models"):
            result["lyrics_models"] = lyrics_out["models"]
        if lyrics_out.get("cleaned"):
            result["lyrics_cleaned"] = True
        # Phase 5b romanisation (display aid; canonical stays native-script)
        try:
            from pipeline.cleanup import romanise_lines

            result["lyric_lines_roman"] = [
                {"timestamp": l["timestamp"], "end": l.get("end"),
                 "text": l.get("roman", l.get("text", ""))}
                for l in romanise_lines(
                    lyrics_out.get("lines", []),
                    lyrics_out.get("language") or language,
                )
            ] if lyrics_out.get("lines") else []
        except Exception:
            result["lyric_lines_roman"] = []
        if lyrics_out.get("error"):
            result["lyrics_error"] = lyrics_out["error"]
    else:
        result["lyrics"] = []
        result["lyric_lines"] = []
        result["lyrics_error"] = "disabled"
        result["lyrics_source"] = "asr"

    _publish_progress(redis_conn, job_id, "done", 1.0)
    try:
        result["job_wall_s"] = round(_time.time() - _job_t0, 1)
    except Exception:
        pass
    print(
        f"job {job_id} done in {result.get('job_wall_s')}s "
        f"source={result.get('lyrics_source')} stages={result.get('lyrics_stages')} "
        f"models={result.get('lyrics_models')} chords={len(result.get('chords', []))} "
        f"words={len(result.get('lyrics', []))}",
        flush=True,
    )
    redis_conn.setex(f"result:{job_id}", _RESULT_TTL, json.dumps(result))
    redis_conn.setex(f"uri:{job_id}", _RESULT_TTL, audio_uri)

    return result


if __name__ == "__main__":
    import logging as _logging

    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    redis_conn = redis.from_url(REDIS_URL)
    q = Queue("chord_jobs", connection=redis_conn)
    worker = Worker([q], connection=redis_conn)
    print("Worker started. Listening on queue: chord_jobs")
    print(f"UPLOAD_DIR={storage.UPLOAD_DIR}")
    print(f"CHORD_ENGINE={os.getenv('CHORD_ENGINE', 'auto')}")
    print(f"ENABLE_LYRICS={os.getenv('ENABLE_LYRICS', '1')}")
    print(f"WHISPER_MODEL={os.getenv('WHISPER_MODEL', 'small')}")
    worker.work()
