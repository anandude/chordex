"""
main.py
-------
FastAPI application — Chordex backend API.

Endpoints:
    POST /api/analyze            Upload audio → enqueue job → return {job_id}
    POST /api/analyze-url        YouTube link → fetch audio → same as upload
    GET  /api/status/{job_id}    Poll job status / result
    GET  /api/audio/{job_id}     Stream uploaded audio for playback (while available)
    GET  /api/library            This device's saved songs (metadata only)
    GET  /api/library/{job_id}   One saved song, with its full result payload
    DELETE /api/library/{job_id} Forget one saved song
    GET  /health                 Uptime health check
"""

import json
import logging
import os
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import redis
from dotenv import load_dotenv
from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job

import library
import storage

load_dotenv()
logger = logging.getLogger(__name__)


# ── App setup ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Create the library table when a database is configured (no-op without).

    Kept off the request path so a slow/absent Neon compute never delays a
    request; the store is best-effort everywhere anyway.
    """
    await run_in_threadpool(library.init)
    yield


app = FastAPI(title="Chordex API", version="2.0.0", lifespan=lifespan)

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
# YouTube audio is ~1 MB/min; the duration cap (youtube.MAX_DURATION_S) is
# the real limit, this only guards against a pathological stream.
_MAX_YT_BYTES = 200 * 1024 * 1024
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
    #: True when the live job has expired and this is the browser's saved copy
    #: from the library. There is no audio behind it, so the UI hides the player.
    from_library: bool = False


@app.post("/api/analyze", response_model=AnalyzeResponse, status_code=202)
async def analyze(
    file: UploadFile = File(...),
    language: str | None = Form(default=None),
    title: str | None = Form(default=None),  # Phase 2: raises LRCLIB hits
    artist: str | None = Form(default=None),
    album: str | None = Form(default=None),
    device_id: str | None = Form(default=None),  # owner for the song library
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
    if file.filename:
        _redis_kv.setex(f"name:{job_id}", _RESULT_TTL, Path(file.filename).stem)
    # stored copy is audio.<ext>; the original name feeds LRCLIB lookup
    _store_and_enqueue(
        job_id, contents, ext, language,
        filename=Path(file.filename or "").name or None,
        meta={"title": title, "artist": artist, "album": album},
        device_id=device_id,
    )
    return AnalyzeResponse(job_id=job_id)


class AnalyzeUrlRequest(BaseModel):
    url: str
    language: str | None = None
    title: str | None = None
    artist: str | None = None
    device_id: str | None = None  # owner for the song library


@app.post("/api/analyze-url", response_model=AnalyzeResponse, status_code=202)
async def analyze_url(req: AnalyzeUrlRequest):
    """Fetch a YouTube video's audio, then analyse it exactly like an upload.

    The download runs here (a few seconds) rather than in a worker so a bad
    link fails the request immediately instead of failing two queued jobs.
    """
    import youtube

    if not youtube.is_youtube_url(req.url):
        raise HTTPException(status_code=400, detail="Only YouTube links are supported.")
    with tempfile.TemporaryDirectory(prefix="chordex_yt_") as tmp:
        try:
            path, hints = await run_in_threadpool(youtube.fetch_audio, req.url, Path(tmp))
        except youtube.YouTubeError as exc:
            logger.warning("analyze-url %s failed: %s", req.url, exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        contents = path.read_bytes()
        ext = path.suffix.lstrip(".").lower()
    if len(contents) > _MAX_YT_BYTES:
        raise HTTPException(status_code=413, detail="Downloaded audio is too large.")

    job_id = str(uuid.uuid4())
    _store_and_enqueue(
        job_id, contents, ext, req.language,
        filename=f"{hints['name']}.{ext}",
        meta={
            # user-typed fields win over YouTube's music metadata
            "title": req.title or hints.get("title"),
            "artist": req.artist or hints.get("artist"),
        },
        device_id=req.device_id,
    )
    _redis_kv.setex(f"name:{job_id}", _RESULT_TTL, hints["name"])
    return AnalyzeResponse(job_id=job_id)


def _store_and_enqueue(
    job_id: str,
    contents: bytes,
    ext: str,
    language: str | None,
    *,
    filename: str | None,
    meta: dict[str, str | None],
    device_id: str | None = None,
) -> None:
    try:
        uri = storage.save_upload(job_id, contents, ext)
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to store upload: {exc}"
        ) from exc

    # Remember URI so we can serve audio during the result TTL window
    _redis_kv.setex(f"uri:{job_id}", _URI_TTL, uri)
    # Remember the owner so the finished song can be filed into their library
    if library.valid_device_id(device_id):
        _redis_kv.setex(f"device:{job_id}", _RESULT_TTL, device_id)

    lang = (language or "").strip().lower() or None
    meta = {k: (v or "").strip() or None for k, v in meta.items()}
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
        kwargs={
            "language": lang,
            "filename": filename,
            **{k: v for k, v in meta.items() if v},
        },
        job_id=f"{job_id}:lyrics",
        job_timeout=_job_timeout(),
    )


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


def _romanise_sheet(sheet: dict, lang: str | None) -> None:
    """Word-level everyday romanisation (pipeline/romanise.py) for any Indic
    script, so the Roman view keeps every chord on its syllable: ``roman`` is
    the whole word, ``roman_segs`` its split across the sheet segments.
    Script-detected per word, so a mis-detected language doesn't matter."""
    try:
        from pipeline.romanise import romanise, romanise_segments, script_of

        for row in sheet["rows"]:
            if row.get("kind") != "line":
                continue
            for w in row["words"]:
                if script_of(w["text"]) is None:
                    continue
                w["roman"] = romanise(w["text"])
                if len(w["segs"]) > 1:
                    w["roman_segs"] = romanise_segments([s["text"] for s in w["segs"]])
    except Exception as exc:  # ImportError (no aksharamukha) → native only
        logger.warning("romanisation unavailable (%s)", exc)


def _attach_sheet(job_id: str, result: dict) -> None:
    """L2: merge chords + lyric timing into the chord sheet (pipeline/sheet).

    Pure and cheap, so it runs at read time — no race between the chord and
    lyrics jobs. Cached once lyrics are final; while they are pending the
    sheet is chords-only and rebuilt on the next poll.
    """
    final = result.get("lyrics_status") in ("done", "failed", "disabled")
    if final:
        cached = _redis_kv.get(f"sheet:{job_id}")
        if cached:
            result["sheet"] = json.loads(cached)
            return
    try:
        from pipeline.sheet import build_sheet

        sheet = build_sheet(
            result.get("chords") or [],
            result.get("lyrics") or [],
            result.get("lyric_lines") or [],
            beats=result.get("beats"),
            tempo=result.get("tempo"),
        )
    except Exception as exc:  # never break status polling over the sheet
        result["sheet_error"] = str(exc)[:300]
        return
    _romanise_sheet(sheet, result.get("lyrics_language"))
    result["sheet"] = sheet
    if final:
        try:
            _redis_kv.setex(f"sheet:{job_id}", _RESULT_TTL, json.dumps(sheet))
        except Exception:
            pass


def _library_state(result: dict) -> str:
    """``final`` once lyrics have settled, ``partial`` before that.

    A partial save files the chord sheet as soon as chords are ready, so a
    visitor who closes the tab during the lyrics job still keeps the song; the
    row is refreshed once lyrics land (or fail).
    """
    settled = result.get("lyrics_status") in ("done", "failed", "disabled")
    return "final" if settled else "partial"


def _save_to_library(job_id: str, device_id: str, state: str, result: dict) -> None:
    """Background task: file a finished song into its owner's library."""
    if library.save(job_id, device_id, result):
        try:
            _redis_kv.setex(f"libsaved:{job_id}", _RESULT_TTL, state)
        except Exception:
            pass


def _library_update(job_id: str, result: dict) -> tuple[str, str, dict] | None:
    """(device_id, state, result) when the stored copy is out of date.

    One Redis read per poll; the write itself runs in a background task so a
    cold Neon compute never delays the status response. Each job is written at
    most twice (chords-only, then once lyrics settle).
    """
    if not library.enabled():
        return None
    try:
        device_id = _redis_kv.get(f"device:{job_id}")
        if not device_id:
            return None
        state = _library_state(result)
        if _redis_kv.get(f"libsaved:{job_id}") == state:
            return None
    except Exception:
        return None
    return device_id, state, result


@app.get("/api/status/{job_id}", response_model=StatusResponse)
async def get_status(
    job_id: str,
    background_tasks: BackgroundTasks,
    x_device_id: str | None = Header(default=None),
):
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
        _attach_sheet(job_id, result)
        name = _redis_kv.get(f"name:{job_id}")
        if name:
            result["source_name"] = name
        resp = StatusResponse(status="done", result=result)
        pending = _library_update(job_id, result)
        if pending:
            device_id, state, snapshot = pending
            background_tasks.add_task(
                _save_to_library, job_id, device_id, state, snapshot
            )
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
        # Redis keeps a finished result for an hour; the library keeps it for
        # good. Serve this browser's saved copy rather than a 404, which is how
        # a song reopened from "your songs" still renders.
        if library.valid_device_id(x_device_id):
            saved = await run_in_threadpool(library.get_song, job_id, x_device_id)
            if saved and saved.get("payload"):
                return StatusResponse(
                    status="done", result=saved["payload"], from_library=True
                )
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
        pipe.delete(f"result:{job_id}", f"lyrics:{job_id}", f"progress:{job_id}",
                    f"sheet:{job_id}")
        pipe.setex(f"cancelled:{job_id}", _RESULT_TTL, "1")
        pipe.execute()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cancel failed: {exc}") from exc
    return {"job_id": job_id, "status": "cancelled"}


def _byte_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Parse a single ``bytes=a-b`` / ``bytes=a-`` / ``bytes=-n`` range."""
    if not header or not header.startswith("bytes=") or "," in header:
        return None
    a, _, b = header[len("bytes="):].strip().partition("-")
    try:
        if a == "":
            n = int(b)
            start, end = max(0, size - n), size - 1
        else:
            start = int(a)
            end = min(int(b), size - 1) if b else size - 1
    except ValueError:
        return None
    if start > end or start >= size:
        return None
    return start, end


@app.get("/api/audio/{job_id}")
async def get_audio(job_id: str, request: Request):
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

    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600"}
    # Honour Range so the player can seek (Safari refuses media without it).
    rng = _byte_range(request.headers.get("range"), len(data))
    if rng is not None:
        start, end = rng
        headers["Content-Range"] = f"bytes {start}-{end}/{len(data)}"
        return Response(content=data[start:end + 1], status_code=206,
                        media_type=content_type, headers=headers)
    return Response(content=data, media_type=content_type, headers=headers)


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
        "library": library.enabled(),
    }


# ── Song library (per anonymous device) ───────────────────────────────────────
# Chordex has no accounts: the browser generates a device id (lib/device.ts)
# and every library read is scoped to it, so nobody can see another visitor's
# songs. There is no cross-device sync, by design.

class SavedSong(BaseModel):
    id: str
    created_at: str | None = None
    source_name: str | None = None
    artist: str | None = None
    key: str | None = None
    tempo: float | None = None
    duration: float | None = None
    engine: str | None = None
    lyrics_language: str | None = None
    lyrics_status: str | None = None
    lyrics_source: str | None = None
    n_chords: int = 0
    has_lyrics: bool = False


class LibraryResponse(BaseModel):
    #: False when the server has no store configured, so the UI can hide the
    #: history section instead of claiming "no songs yet".
    enabled: bool = False
    songs: list[SavedSong] = []


def _owner(device_id: str | None, header: str | None) -> str:
    """Device id from the ``X-Device-Id`` header (preferred) or ``?device_id=``."""
    value = (header or device_id or "").strip()
    if not library.valid_device_id(value):
        raise HTTPException(status_code=400, detail="A valid device_id is required.")
    return value


@app.get("/api/library", response_model=LibraryResponse)
async def list_library(
    device_id: str | None = None,
    x_device_id: str | None = Header(default=None),
):
    """This device's saved songs, newest first (metadata only)."""
    if not library.enabled():
        return LibraryResponse(enabled=False)
    songs = await run_in_threadpool(library.list_songs, _owner(device_id, x_device_id))
    return LibraryResponse(enabled=True, songs=songs)


@app.get("/api/library/{job_id}")
async def get_library_song(
    job_id: str,
    device_id: str | None = None,
    x_device_id: str | None = Header(default=None),
):
    """One saved song with the full result payload (404 if not this device's)."""
    if not library.enabled():
        raise HTTPException(status_code=404, detail="Song not found.")
    song = await run_in_threadpool(library.get_song, job_id, _owner(device_id, x_device_id))
    if song is None:
        raise HTTPException(status_code=404, detail="Song not found.")
    return {"song": song}


@app.delete("/api/library/{job_id}", status_code=202)
async def forget_library_song(
    job_id: str,
    device_id: str | None = None,
    x_device_id: str | None = Header(default=None),
):
    """Forget one saved song. Only the device that saved it can."""
    if not library.enabled():
        raise HTTPException(status_code=404, detail="Song not found.")
    deleted = await run_in_threadpool(
        library.delete_song, job_id, _owner(device_id, x_device_id)
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Song not found.")
    return {"deleted": True}
