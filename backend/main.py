"""
main.py
-------
FastAPI application — ChordLens backend API.

Endpoints:
    POST /api/analyze            Upload audio → enqueue job → return {job_id}
    GET  /api/status/{job_id}    Poll job status / result
    GET  /api/audio/{job_id}     Stream uploaded audio for playback (while available)
    GET  /health                 Uptime health check
"""

import json
import os
import uuid
from pathlib import Path
from typing import Literal

import redis
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job

import storage

load_dotenv()

# ── App setup ─────────────────────────────────────────────────────────────────
app = FastAPI(title="ChordLens API", version="2.0.0")

_allowed_origins = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Redis / RQ ────────────────────────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

_redis_kv = redis.from_url(REDIS_URL, decode_responses=True)
_redis_rq = redis.from_url(REDIS_URL)
# S3: chords (fast) and lyrics (slow) run on separate queues so a
# minutes-long lyrics job never blocks the next song's chord job.
_chord_queue = Queue("chord_jobs", connection=_redis_rq)
_lyrics_queue = Queue("lyrics_jobs", connection=_redis_rq)

# ── Config ────────────────────────────────────────────────────────────────────
_MAX_BYTES = int(os.getenv("MAX_FILE_SIZE_MB", "20")) * 1024 * 1024
_ALLOWED_EXTS = {"mp3", "wav", "ogg", "flac", "m4a"}
_RESULT_TTL = 3600  # 1 hour
_URI_TTL = 3600
_DEFAULT_JOB_TIMEOUT_S = 7200  # 2 h — CPU separation + ASR, plus a one-off
#                               model download on an uncached language
_DEFAULT_CHORD_TIMEOUT_S = 600  # 10 min — chord recognition alone is ~5–60 s;
#                               anything longer means a stuck vamp plugin


def _job_timeout() -> int:
    """RQ job timeout in seconds (``JOB_TIMEOUT_S``).

    RQ hard-kills a job once it exceeds its timeout (it SIGKILLs the work horse
    at ``timeout + 60 s``), which used to fail any first run for hi/ml: the
    per-language ASR fine-tune (~1 GB) was still downloading when the old
    1800 s deadline passed, so the job died reporting "Work-horse terminated
    unexpectedly; waitpid returned None". Long by design; per-stage progress is
    published to ``progress:{job_id}`` while the job runs.
    """
    try:
        return int(os.getenv("JOB_TIMEOUT_S", str(_DEFAULT_JOB_TIMEOUT_S)))
    except ValueError:
        return _DEFAULT_JOB_TIMEOUT_S


def _chord_timeout() -> int:
    """RQ timeout for the fast chord-only job (``CHORD_TIMEOUT_S``)."""
    try:
        return int(os.getenv("CHORD_TIMEOUT_S", str(_DEFAULT_CHORD_TIMEOUT_S)))
    except ValueError:
        return _DEFAULT_CHORD_TIMEOUT_S


class AnalyzeResponse(BaseModel):
    job_id: str


class StatusResponse(BaseModel):
    status: Literal["queued", "processing", "done", "failed", "cancelled"]
    result: dict | None = None
    error: str | None = None
    stage: str | None = None  # pipeline progress: separating → … → done
    progress: float | None = None
    # Queue visibility: which queue the awaited job waits in, 1-indexed
    # position, and total queued depth (both None when not waiting).
    queue_name: str | None = None
    queue_position: int | None = None
    queue_depth: int | None = None


@app.post("/api/analyze", response_model=AnalyzeResponse, status_code=202)
async def analyze(
    file: UploadFile = File(...),
    language: str | None = Form(default=None),
    title: str | None = Form(default=None),  # Phase 2: raises LRCLIB hits
    artist: str | None = Form(default=None),
    album: str | None = Form(default=None),
):
    """Accept an audio upload, store it, enqueue analysis, return a job ID."""
    ext = Path(file.filename or "").suffix.lstrip(".").lower()
    if ext not in _ALLOWED_EXTS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type '{ext}'. "
                f"Allowed: {', '.join(sorted(_ALLOWED_EXTS))}"
            ),
        )

    contents = await file.read()
    if len(contents) > _MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File too large. Maximum allowed size is "
                f"{_MAX_BYTES // (1024 * 1024)} MB."
            ),
        )

    job_id = str(uuid.uuid4())
    try:
        uri = storage.save_upload(job_id, contents, ext)
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to store upload: {exc}"
        ) from exc

    # Remember URI so we can serve audio during the result TTL window
    _redis_kv.setex(f"uri:{job_id}", _URI_TTL, uri)

    lang = (language or "").strip().lower() or None
    meta = {
        k: (v or "").strip() or None
        for k, v in (("title", title), ("artist", artist), ("album", album))
    }
    # S3: split enqueue — chords first (fast, renders in seconds), lyrics
    # second (slow). RQ job ids are namespaced so both can be tracked.
    _chord_queue.enqueue(
        "worker.run_chords",
        args=(uri,),
        job_id=f"{job_id}:chords",
        job_timeout=_chord_timeout(),
    )
    _lyrics_queue.enqueue(
        "worker.run_lyrics",
        args=(uri,),
        kwargs={"language": lang, **{k: v for k, v in meta.items() if v}},
        job_id=f"{job_id}:lyrics",
        job_timeout=_job_timeout(),
    )

    return AnalyzeResponse(job_id=job_id)


def _job_progress(job_id: str) -> tuple[str | None, float | None]:
    try:
        raw = _redis_kv.get(f"progress:{job_id}")
        if raw:
            data = json.loads(raw)
            return data.get("stage"), data.get("pct")
    except Exception:
        pass
    return None, None


def _fetch_job(rq_id: str) -> Job | None:
    try:
        return Job.fetch(rq_id, connection=_redis_rq)
    except NoSuchJobError:
        return None


def _queue_info(rq_id: str, queue: Queue) -> tuple[str | None, int | None, int | None]:
    """(queue_name, 1-indexed position, queued depth) for a waiting job.

    Position comes from RQ (None once the job leaves the queue); depth is a
    best-effort len() so the UI can say "#N of M". Never raises.
    """
    job = _fetch_job(rq_id) or _fetch_job(rq_id.split(":")[0])
    if job is None:
        return None, None, None
    try:
        pos = job.get_position()
        position = (pos + 1) if pos is not None else None
    except Exception:
        position = None
    try:
        depth = len(queue)
    except Exception:
        depth = None
    if position is None and (depth is None or depth == 0):
        return None, None, None
    return queue.name, position, depth


def _is_cancelled(job_id: str) -> bool:
    try:
        return bool(_redis_kv.get(f"cancelled:{job_id}"))
    except Exception:
        return False


def _lyrics_state(job_id: str) -> tuple[str, str | None]:
    """Resolve (lyrics_status, lyrics_error) once chords are cached.

    Lyrics never fail the overall job: a dead lyrics worker surfaces as
    lyrics_status=failed with the (truncated) error for the UI, while the
    chords already shown stay put.
    """
    from lyrics_transcriber import lyrics_enabled

    if not lyrics_enabled():
        return "disabled", "disabled"
    if _redis_kv.get(f"lyrics:{job_id}"):
        return "done", None
    job = _fetch_job(f"{job_id}:lyrics")
    if job is None:
        # Lyrics job not enqueued (yet) — treat as pending, not an error.
        return "pending", None
    if job.is_failed:
        error_msg = "Lyrics job failed without a traceback."
        if job.exc_info:
            error_msg = str(job.exc_info)[-500:]
        return "failed", error_msg
    if job.is_started:
        return "processing", None
    return "pending", None


@app.get("/api/status/{job_id}", response_model=StatusResponse)
async def get_status(job_id: str):
    """Poll the status of a chord-analysis job.

    S3 staged delivery: returns ``done`` as soon as the fast chord job is
    cached (seconds), with ``result.lyrics_status`` tracking the slow lyrics
    job (pending → processing → done/failed/disabled). The frontend renders
    chords immediately and keeps polling while lyrics are unfinished.
    """
    cached = _redis_kv.get(f"result:{job_id}")
    if cached:
        result = json.loads(cached)
        lyrics_cached = _redis_kv.get(f"lyrics:{job_id}")
        if lyrics_cached:
            result.update(json.loads(lyrics_cached))
            result["lyrics_status"] = "done"
        else:
            state, error = _lyrics_state(job_id)
            result["lyrics_status"] = state
            if state == "failed" and error and not result.get("lyrics_error"):
                result["lyrics_error"] = error
        resp = StatusResponse(status="done", result=result)
        if result.get("lyrics_status") in ("pending", "processing"):
            qn, qp, qd = _queue_info(f"{job_id}:lyrics", _lyrics_queue)
            resp.queue_name, resp.queue_position, resp.queue_depth = qn, qp, qd
        return resp

    if _is_cancelled(job_id):
        return StatusResponse(status="cancelled")

    # Chords not cached yet — inspect the chord job (plus a legacy fallback
    # for jobs enqueued before the S3 split, which used the bare job_id).
    job = _fetch_job(f"{job_id}:chords") or _fetch_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")

    if job.is_queued:
        qn, qp, qd = _queue_info(f"{job_id}:chords", _chord_queue)
        return StatusResponse(status="queued", queue_name=qn,
                              queue_position=qp, queue_depth=qd)
    if job.is_started:
        stage, pct = _job_progress(job_id)
        qn, qp, qd = _queue_info(f"{job_id}:chords", _chord_queue)
        return StatusResponse(status="processing", stage=stage or "processing",
                              progress=pct, queue_name=qn,
                              queue_position=qp, queue_depth=qd)
    if job.is_failed:
        error_msg = "Job failed without a traceback."
        if job.exc_info:
            error_msg = str(job.exc_info)[-500:]
        return StatusResponse(status="failed", error=error_msg)
    if job.is_finished:
        result = job.result
        if isinstance(result, dict):
            result.setdefault("lyrics_status", "pending")
            return StatusResponse(status="done", result=result)
        cached = _redis_kv.get(f"result:{job_id}")
        if cached:
            return StatusResponse(status="done", result=json.loads(cached))
        return StatusResponse(status="done", result=None)

    return StatusResponse(status="queued")


@app.delete("/api/jobs/{job_id}", status_code=202)
async def cancel_job(job_id: str):
    """Cancel a queued/processing job.

    Dequeues both RQ jobs (a running horse finishes harmlessly — its output
    is ignored once the cancelled marker is set), drops cached partials, and
    records the marker so GET /api/status reports "cancelled" instead of
    resurrecting the job from a late write.
    """
    for rq_id in (f"{job_id}:chords", f"{job_id}:lyrics", job_id):
        try:
            job = _fetch_job(rq_id)
            if job is not None:
                job.cancel()
        except Exception:
            pass
    try:
        pipe = _redis_kv.pipeline()
        pipe.delete(f"result:{job_id}", f"lyrics:{job_id}", f"progress:{job_id}")
        pipe.setex(f"cancelled:{job_id}", _RESULT_TTL, "1")
        pipe.execute()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cancel failed: {exc}") from exc
    return {"job_id": job_id, "status": "cancelled"}


@app.get("/api/audio/{job_id}")
async def get_audio(job_id: str):
    """Stream the uploaded audio for in-browser playback (while still stored)."""
    uri = _redis_kv.get(f"uri:{job_id}")
    if not uri:
        uri = storage.uri_for_job(job_id)
    if not uri:
        raise HTTPException(
            status_code=404,
            detail="Audio not found (expired or never uploaded).",
        )
    try:
        data = storage.get_bytes(uri)
        content_type = storage.get_content_type(uri)
    except Exception as exc:
        raise HTTPException(
            status_code=404, detail=f"Audio unavailable: {exc}"
        ) from exc

    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "private, max-age=3600",
        },
    )


@app.get("/health")
async def health():
    """Lightweight health check used by Render's uptime monitor."""
    redis_ok = False
    try:
        redis_ok = bool(_redis_kv.ping())
    except Exception:
        redis_ok = False
    return {
        "status": "ok" if redis_ok else "degraded",
        "redis": redis_ok,
        "engine": os.getenv("CHORD_ENGINE", "auto"),
        "jobs": "split (chord_jobs + lyrics_jobs)",
        "chord_timeout": _chord_timeout(),
        "lyrics": os.getenv("ENABLE_LYRICS", "1"),
        "whisper_model": os.getenv("WHISPER_MODEL", "small"),
        "separation": os.getenv("LYRICS_SEPARATION_BACKEND", "demucs"),
        "lrclib": os.getenv("LYRICS_LRCLIB", "1"),
        "alignment": os.getenv("LYRICS_ALIGNMENT", "1"),
        "chord_meta": os.getenv("CHORD_META", "1"),
        "snap_to_beats": os.getenv("SNAP_TO_BEATS", "1"),
        "chroma": f"{os.getenv('CHROMA_KIND', 'cqt')}/{os.getenv('CHROMA_HOP', '2048')}",
    }
