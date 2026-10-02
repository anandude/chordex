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

# Side-effect import: keeps huggingface_hub off the xet transfer backend (which
# stalls on some networks) before any job loads a model — pipeline/hf_setup.py.
from pipeline import hf_setup  # noqa: F401

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


def _job_id_from_uri(audio_uri: str) -> str:
    """Uploads are stored at <UPLOAD_DIR>/<job_id>/audio.<ext> — recover it."""
    if audio_uri.startswith("file://"):
        path = Path(audio_uri[len("file://") :])
        return path.parent.name
    elif audio_uri.startswith("s3://"):
        key = audio_uri.split("s3://", 1)[1].split("/", 1)[1]
        return Path(key).parent.name
    else:
        return Path(audio_uri).parent.name


def run_chords(audio_uri: str) -> dict:
    """S3: fast chord-only job (~5–10 s).

    Caches the chord result immediately so the UI renders without waiting
    for the (minutes-long) lyrics job. Lyrics arrive later via run_lyrics
    and are merged by GET /api/status.
    """
    from chord_detector import detect_chords
    from easy_chords import apply_easy_mode

    job_id = _job_id_from_uri(audio_uri)

    import time as _time

    local_path = storage.resolve_path(audio_uri)
    redis_conn = redis.from_url(REDIS_URL, decode_responses=True)
    _job_t0 = _time.time()
    _publish_progress(redis_conn, job_id, "chords", 0.05)
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

    # Lyrics fields are filled in later by run_lyrics (or never, if disabled).
    result["lyrics"] = []
    result["lyric_lines"] = []
    result["lyrics_status"] = "pending"
    try:
        result["job_wall_s"] = round(_time.time() - _job_t0, 1)
    except Exception:
        pass
    print(
        f"job {job_id} chords done in {result.get('job_wall_s')}s "
        f"engine={result.get('engine')} chords={len(result.get('chords', []))}",
        flush=True,
    )
    redis_conn.setex(f"result:{job_id}", _RESULT_TTL, json.dumps(result))
    redis_conn.setex(f"uri:{job_id}", _RESULT_TTL, audio_uri)

    return result


def run_lyrics(
    audio_uri: str,
    language: str | None = None,
    title: str | None = None,
    artist: str | None = None,
    album: str | None = None,
) -> dict:
    """S3: slow lyrics-only job (separate → lookup/ASR → align → clean).

    Best-effort by design: any failure is captured in the cached payload as
    lyrics_status=failed + lyrics_error, so chords already shown are never
    taken away. Duration is read from the (already cached) chord result when
    available, else probed by the transcriber itself.
    """
    from lyrics_transcriber import lyrics_enabled, transcribe_lyrics

    job_id = _job_id_from_uri(audio_uri)

    import time as _time

    local_path = storage.resolve_path(audio_uri)
    redis_conn = redis.from_url(REDIS_URL, decode_responses=True)
    _job_t0 = _time.time()

    lyrics: dict = {
        "lyrics": [],
        "lyric_lines": [],
        "lyrics_status": "pending",
        "lyrics_source": "asr",
    }

    if not lyrics_enabled():
        lyrics["lyrics_status"] = "disabled"
        lyrics["lyrics_error"] = "disabled"
    else:
        _publish_progress(redis_conn, job_id, "separating", 0.15)

        def _on_stage(stage: str, pct: float) -> None:
            _publish_progress(redis_conn, job_id, stage, pct)

        # Prefer the chord job's duration (already computed); the transcriber
        # probes it itself when absent (e.g. chord job still running).
        duration = None
        try:
            cached = redis_conn.get(f"result:{job_id}")
            if cached:
                duration = json.loads(cached).get("duration")
        except Exception:
            duration = None

        try:
            lyrics_out = transcribe_lyrics(
                local_path, language=language, title=title, artist=artist,
                album=album, duration=duration, progress=_on_stage,
            )
            lyrics["lyrics"] = lyrics_out.get("lyrics", [])
            lyrics["lyric_lines"] = lyrics_out.get("lines", [])
            lyrics["lyrics_language"] = lyrics_out.get("language")
            lyrics["lyrics_source"] = lyrics_out.get("source", "asr")
            if lyrics_out.get("stages"):
                lyrics["lyrics_stages"] = lyrics_out["stages"]
            if lyrics_out.get("models"):
                lyrics["lyrics_models"] = lyrics_out["models"]
            if lyrics_out.get("cleaned"):
                lyrics["lyrics_cleaned"] = True
            # Phase 5b romanisation (display aid; canonical stays native-script)
            try:
                from pipeline.cleanup import romanise_lines

                lyrics["lyric_lines_roman"] = [
                    {"timestamp": l["timestamp"], "end": l.get("end"),
                     "text": l.get("roman", l.get("text", ""))}
                    for l in romanise_lines(
                        lyrics_out.get("lines", []),
                        lyrics_out.get("language") or language,
                    )
                ] if lyrics_out.get("lines") else []
            except Exception:
                lyrics["lyric_lines_roman"] = []
            if lyrics_out.get("error"):
                lyrics["lyrics_error"] = lyrics_out["error"]
            lyrics["lyrics_status"] = "done"
        except Exception as exc:
            lyrics["lyrics_status"] = "failed"
            lyrics["lyrics_error"] = str(exc)[-500:]

    _publish_progress(redis_conn, job_id, "done", 1.0)
    try:
        lyrics["lyrics_wall_s"] = round(_time.time() - _job_t0, 1)
    except Exception:
        pass
    print(
        f"job {job_id} lyrics {lyrics.get('lyrics_status')} in "
        f"{lyrics.get('lyrics_wall_s')}s "
        f"source={lyrics.get('lyrics_source')} "
        f"words={len(lyrics.get('lyrics', []))}",
        flush=True,
    )
    redis_conn.setex(f"lyrics:{job_id}", _RESULT_TTL, json.dumps(lyrics))

    return lyrics


if __name__ == "__main__":
    import logging as _logging
    import sys as _sys

    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    redis_conn = redis.from_url(REDIS_URL)
    # S3: chords and lyrics run on separate queues so a minutes-long lyrics
    # job never head-of-line-blocks the next song's ~10 s chord job.
    # Default serves both (chords first); scale out with e.g.
    #   python worker.py lyrics_jobs        # lyrics-only process
    #   python worker.py chord_jobs         # chords-only process
    # (One lyrics worker per GPU/RAM budget — each process loads its own
    # demucs + whisper weights.)
    wanted = _sys.argv[1:] or ["chord_jobs", "lyrics_jobs"]
    queues = [Queue(name, connection=redis_conn) for name in wanted]
    worker = Worker(queues, connection=redis_conn)
    print(f"Worker started. Listening on queues: {', '.join(wanted)}")
    print(f"UPLOAD_DIR={storage.UPLOAD_DIR}")
    print(f"CHORD_ENGINE={os.getenv('CHORD_ENGINE', 'auto')}")
    print(f"CHORD_SOURCE={os.getenv('CHORD_SOURCE', 'mix')}")
    print(f"KEY_AWARE={os.getenv('KEY_AWARE', '0')}")
    print(f"CHORD_META={os.getenv('CHORD_META', '1')}")
    print(f"SNAP_TO_BEATS={os.getenv('SNAP_TO_BEATS', '1')}")
    print(f"CHROMA_KIND={os.getenv('CHROMA_KIND', 'cqt')}")
    print(f"ENABLE_LYRICS={os.getenv('ENABLE_LYRICS', '1')}")
    print(f"WHISPER_MODEL={os.getenv('WHISPER_MODEL', 'small')}")
    worker.work()
