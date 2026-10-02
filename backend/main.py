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
_queue = Queue("chord_jobs", connection=_redis_rq)

# ── Config ────────────────────────────────────────────────────────────────────
_MAX_BYTES = int(os.getenv("MAX_FILE_SIZE_MB", "20")) * 1024 * 1024
_ALLOWED_EXTS = {"mp3", "wav", "ogg", "flac", "m4a"}
_RESULT_TTL = 3600  # 1 hour
_URI_TTL = 3600


class AnalyzeResponse(BaseModel):
    job_id: str


class StatusResponse(BaseModel):
    status: Literal["queued", "processing", "done", "failed"]
    result: dict | None = None
    error: str | None = None
    stage: str | None = None  # pipeline progress: separating → … → done
    progress: float | None = None


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
    _queue.enqueue(
        "worker.run_chord_detection",
        args=(uri,),
        kwargs={"language": lang, **{k: v for k, v in meta.items() if v}},
        job_id=job_id,
        job_timeout=1800,  # separation + Indic models are slow on CPU
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


@app.get("/api/status/{job_id}", response_model=StatusResponse)
async def get_status(job_id: str):
    """Poll the status of a chord-analysis job."""
    cached = _redis_kv.get(f"result:{job_id}")
    if cached:
        return StatusResponse(status="done", result=json.loads(cached))

    try:
        job = Job.fetch(job_id, connection=_redis_rq)
    except NoSuchJobError as exc:
        raise HTTPException(status_code=404, detail="Job not found.") from exc

    if job.is_queued:
        return StatusResponse(status="queued")
    if job.is_started:
        stage, pct = _job_progress(job_id)
        return StatusResponse(status="processing", stage=stage or "processing",
                              progress=pct)
    if job.is_failed:
        error_msg = "Job failed without a traceback."
        if job.exc_info:
            error_msg = str(job.exc_info)[-500:]
        return StatusResponse(status="failed", error=error_msg)
    if job.is_finished:
        result = job.result
        if result:
            return StatusResponse(status="done", result=result)
        cached = _redis_kv.get(f"result:{job_id}")
        if cached:
            return StatusResponse(status="done", result=json.loads(cached))
        return StatusResponse(status="done", result=None)

    return StatusResponse(status="queued")


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
        "lyrics": os.getenv("ENABLE_LYRICS", "1"),
        "whisper_model": os.getenv("WHISPER_MODEL", "small"),
        "separation": os.getenv("LYRICS_SEPARATION_BACKEND", "demucs"),
        "lrclib": os.getenv("LYRICS_LRCLIB", "1"),
        "alignment": os.getenv("LYRICS_ALIGNMENT", "1"),
    }
