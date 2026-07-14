# ChordLens — Guitar Chord Analyzer
### Full Implementation Blueprint
**Stack:** React/Next.js + Python FastAPI · **Hosting:** Vercel + Render + Upstash · **Roadmap:** MVP → v3

---

## Table of Contents
1. [Project Overview & Goals](#1-project-overview--goals)
2. [Architecture Decision & Rationale](#2-architecture-decision--rationale)
3. [MVP Implementation — Phase 1](#3-mvp-implementation--phase-1)
4. [Deployment Guide](#4-deployment-guide-mvp)
5. [Version 2 — Lyrics Transcription](#5-version-2--lyrics-transcription)
6. [Version 3 — Easy/Beginner Chords](#6-version-3--easybeginner-chords)
7. [Known Limitations](#7-known-limitations--how-to-handle-them)
8. [Testing Strategy](#8-testing-strategy)
9. [Exact Implementation Order for Coding Agent](#9-exact-implementation-order-for-coding-agent)
10. [Quick Reference](#10-quick-reference)

---

## 1. Project Overview & Goals

ChordLens accepts any MP3 or WAV audio file and returns a timestamped chord progression that guitarists can read, transpose, and eventually follow along with synchronized lyrics. The architecture is designed so the MVP ships quickly and each subsequent version adds features without rearchitecting.

> 🎯 **Core User Promise:** Upload a song → see every chord with timestamps → transpose to any key → *(later)* read lyrics while the song plays.

### Version Roadmap

| Version | Label | Key Features |
|---------|-------|--------------|
| **MVP** | Chord Detector | Upload audio → timestamped chord progression → transpose UI |
| **v2** | Lyrics Sync | Whisper transcription → lyrics displayed alongside chords with timestamps |
| **v3** | Easy Chords | Capo suggestion + remap complex/barre chords to beginner-friendly open chords |

---

## 2. Architecture Decision & Rationale

### Why a Python backend (not browser-only)?

Audio analysis libraries like `librosa`, `numpy`, and `scipy` are mature Python-first tools with no reliable WebAssembly equivalents. Running chord detection on the server also means users on mobile or low-end devices get full performance. Python is the only practical choice here.

### Chosen Stack

| Layer | Technology | Reason |
|-------|-----------|--------|
| Frontend | Next.js 14 (App Router) | React with built-in routing, SSR for SEO, deploys free on Vercel |
| Backend API | Python FastAPI | Async, fast, auto-docs, great for file upload & long-running jobs |
| Audio Analysis | librosa + numpy + scipy | Industry standard for Music Information Retrieval (MIR) |
| Job Queue | Redis + RQ (Redis Queue) | Lightweight vs Celery; audio processing takes 10–60s so async is required |
| Backend Hosting | Render.com (free tier) | 750 hrs/month free; Docker support; easy deploys from GitHub |
| Redis Hosting | Upstash (free tier) | 10,000 free commands/day; serverless Redis; no infra to manage |
| Frontend Hosting | Vercel | Ideal for Next.js; generous free tier; zero-config deployments |
| File Storage (v2+) | Cloudflare R2 | 10 GB free; no egress fees; S3-compatible API |

> ⚠️ **Render Free Tier Caveat:** Render's free tier spins down after 15 minutes of inactivity — the first request after idle takes ~50 seconds. For MVP/testing this is fine. When you get real users, upgrade to Render Starter ($7/mo) or Railway ($5 credit/mo). Budget: **$0 during development**, ~$7–15/mo at production scale.

### System Flow

```
User uploads file
  → Next.js frontend
  → POST /api/analyze (FastAPI)
  → Saves file to temp storage
  → Enqueues job to Redis
  → Returns { job_id }
  → Frontend polls GET /api/status/{job_id} every 2 seconds
  → RQ Worker picks up job
  → librosa chord detection runs
  → Result saved to Redis (1hr TTL)
  → Frontend gets result
  → Displays chord timeline + transpose UI
```

---

## 3. MVP Implementation — Phase 1

### 3.1 Repository Structure

Use a monorepo with two top-level folders: `/frontend` and `/backend`.

```
chordlens/
  frontend/                   # Next.js 14 app
    app/
      page.tsx                # Upload page
      results/[jobId]/
        page.tsx              # Results + transpose page
    components/
      AudioUploader.tsx
      ChordTimeline.tsx
      TransposeControl.tsx
    lib/
      api.ts                  # API calls to backend
      transpose.ts            # Client-side transpose logic
  backend/                    # Python FastAPI + worker
    main.py                   # FastAPI app
    worker.py                 # RQ worker entry point
    chord_detector.py         # Core analysis logic
    transposer.py             # Chord transposition logic
    requirements.txt
    Dockerfile
  README.md
```

---

### 3.2 Backend — Core Files

#### `requirements.txt`

```
fastapi==0.111.0
uvicorn[standard]==0.29.0
python-multipart==0.0.9
librosa==0.10.1
numpy==1.26.4
scipy==1.13.0
redis==5.0.4
rq==1.16.2
python-dotenv==1.0.1
pydantic==2.7.1
```

---

#### `chord_detector.py` — How the algorithm works

This is the heart of the application. The algorithm has 5 steps:

1. **Load the audio** using `librosa.load()`. Handles both MP3 and WAV automatically.
2. **Apply HPSS (Harmonic-Percussive Source Separation).** Strips drums, hi-hats, and percussion so the chord detector only sees harmonic/tonal content. This significantly improves accuracy.
3. **Extract Chroma CQT features.** Chroma features represent the 12 pitch classes (C, C#, D, …) over time. CQT (Constant-Q Transform) is more musically meaningful than standard FFT for chord detection.
4. **Template matching against chord profiles.** For each time window, compare the chroma vector against stored major and minor chord templates using cosine similarity. The best-matching template is the chord for that segment.
5. **Smooth the chord sequence.** Apply a median filter to eliminate flickering, then run-length encode to output only chord-change events with timestamps.

> 📝 **Coding Agent Note — `chord_detector.py`**
>
> Implement a function: `detect_chords(file_path: str) -> list[dict]`. Each dict: `{timestamp: float, chord: str}`.
>
> - Use `librosa.load()`, `librosa.effects.hpss()`, `librosa.feature.chroma_cqt()`
> - Use `hop_length=4096` (~0.09s windows at 44100Hz)
> - Build 24 chord templates (12 major + 12 minor) using the Krumhansl-Schmuckler key profiles
> - Use **cosine similarity** (not Euclidean distance)
> - Apply `scipy.ndimage.median_filter(size=9)` before extracting change events
> - Filter out chord segments shorter than 1 second
> - Also return `tempo` (BPM) from `librosa.beat.beat_track()`

---

#### `main.py` — FastAPI API structure

Define these endpoints:

- `POST /api/analyze` — accepts multipart form upload (audio file, max 20MB). Saves to `/tmp/{uuid}/audio`, enqueues RQ job, returns `{ job_id: string }`.
- `GET /api/status/{job_id}` — polls RQ job status. Returns `{ status: 'queued'|'processing'|'done'|'failed', result: ChordResult|null, error: string|null }`.
- `GET /health` — simple health check for Render's uptime monitoring.

> 📝 **Coding Agent Note — `main.py`**
>
> - Never block the FastAPI event loop with librosa — use RQ for all heavy work
> - Accept files as `UploadFile`; validate extensions (mp3, wav, ogg, flac only)
> - Set CORS to allow your Vercel domain via `ALLOWED_ORIGINS` env var
> - Store job results in Redis with a **1-hour TTL**
> - Use `python-dotenv` to load `REDIS_URL` from environment

---

#### `transposer.py` — Chord transposition logic

Transposition is pure music theory — no audio reprocessing needed.

Implement: `transpose_progression(chords: list[dict], semitones: int) -> list[dict]`

The 12 chromatic notes: `C, C#, D, D#, E, F, F#, G, G#, A, A#, B`

To transpose: find the root note's index → add semitone offset (mod 12) → look up new root. Preserve the chord quality (major, minor, 7, sus4, etc.) — only the root changes.

> 📝 **Coding Agent Note — `transposer.py`**
>
> - Build a `NOTES` list of 12 chromatic pitches
> - Parse a chord string like `'Am7'` into root (`'A'`) + quality (`'m7'`)
> - Find root index, add semitones mod 12, reconstruct
> - Prefer sharps (`C#`) over flats (`Db`) for guitar contexts
> - Handle the special chord `'N'` (no chord) by passing through unchanged

---

#### `worker.py` — RQ worker

The worker process is separate from the FastAPI process. It runs in an infinite loop picking jobs off the Redis queue and executing chord detection.

On Render, run both processes: the web process (`uvicorn main:app`) and the worker process (`python worker.py`) — either from the same Docker container using a Procfile, or as two separate Render services (recommended).

---

### 3.3 Frontend — Key Components

#### `app/page.tsx` — Upload Page

The home page contains a single clean upload area:
- Drag-and-drop zone accepting MP3/WAV files up to 20MB
- On file select, POST the file to `/api/analyze`
- Redirect to `/results/{jobId}` immediately (don't wait for processing)

#### `app/results/[jobId]/page.tsx` — Results Page

- Poll `GET /api/status/{jobId}` every 2 seconds while status is `queued` or `processing`
- Show a loading spinner with estimated wait time
- Once done, render `ChordTimeline` and `TransposeControl`

#### `components/ChordTimeline.tsx`

- Scrollable horizontal timeline of chord cards
- Each card shows timestamp + chord name
- Color-coded by quality: major = blue, minor = purple, other = gray
- On mobile: render as a vertical list

#### `components/TransposeControl.tsx`

- A -6 to +6 semitone slider (or +/- buttons)
- Transposition happens **client-side** using `transpose.ts` — no second API call
- Show transposed key name (e.g. `"Transposed +2 semitones: now in D major"`)

#### `lib/transpose.ts`

Mirror the Python transposer logic in TypeScript. The frontend does transposition locally so the UI is instant and no extra server load is needed.

> 📝 **Coding Agent Note — Frontend**
>
> - Use **TailwindCSS** for styling
> - Use **React Query** (`@tanstack/react-query`) for polling — handles retries and caching cleanly
> - Use a 2-second polling interval with exponential backoff on errors
> - Show only chord *changes* (don't repeat the same chord consecutively)
> - Display the **BPM** detected by librosa as a bonus stat alongside the progression

---

### 3.4 Dockerfile (Backend)

The backend needs `ffmpeg` installed system-wide — librosa uses it to decode MP3s.

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

> ❌ **Critical — ffmpeg:** `librosa` cannot decode MP3 files without `ffmpeg` installed. This is the **most common deployment failure**. Always install `ffmpeg` in the Dockerfile *before* installing Python packages.

---

### 3.5 Environment Variables

| Variable | Set In | Value |
|----------|--------|-------|
| `REDIS_URL` | Render env | Your Upstash Redis connection string (`rediss://...`) |
| `NEXT_PUBLIC_API_URL` | Vercel env | `https://your-backend.onrender.com` |
| `ALLOWED_ORIGINS` | Render env | `https://your-app.vercel.app` |
| `MAX_FILE_SIZE_MB` | Render env | `20` |

---

## 4. Deployment Guide (MVP)

Follow this order:

1. **Upstash Redis** — Create account at [upstash.com](https://upstash.com). Create a Redis database. Copy the connection string formatted as: `rediss://:PASSWORD@ENDPOINT:PORT`

2. **Render — Web Service** — Push `backend/` to GitHub. Connect to Render. Create a Web Service with Docker runtime. Set env vars. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`

3. **Render — Worker Service** — Create a second Render service from the same repo. Start command: `python worker.py`. This is your RQ worker running separately from the API.

4. **Vercel — Frontend** — Import `frontend/` to Vercel. Set `NEXT_PUBLIC_API_URL` to your Render backend URL. Deploy.

5. **End-to-end test** — Upload a short MP3, verify polling works, verify chords appear.

> 💡 **Tip — Two Render Services vs One:** Run the FastAPI web server and the RQ worker as two separate Render services from the same GitHub repo with different start commands. This prevents slow audio jobs from blocking API responses. Both run on the free tier simultaneously.

---

## 5. Version 2 — Lyrics Transcription

### Approach & Library Choice

Use OpenAI Whisper via the `faster-whisper` library (a 4× faster drop-in replacement). `faster-whisper` returns **word-level timestamps** out of the box. Run this in the same async job pipeline as chord detection.

> 📝 **Coding Agent Note — Lyrics (v2)**
>
> - Add `lyrics_transcriber.py`. Use `faster-whisper` (`pip install faster-whisper`).
> - Load the `'base'` or `'small'` model for cost/speed balance on CPU
> - Call `model.transcribe(audio_path, word_timestamps=True)`
> - Returns segments, each with `start`, `end`, and `words` (list of word + timestamp)
> - Flatten to a list of `{timestamp: float, word: str}` dicts
> - Add `lyrics` field alongside chord output in the same job result JSON

### Frontend Changes for v2

- Add `LyricsDisplay` component — shows lyrics line-by-line with timestamps
- When the user plays the audio (HTML `<audio>` element), highlight the current word using `ontimeupdate` — compare `audio.currentTime` to each word's timestamp
- Show chords and lyrics side-by-side or stacked, aligned temporally
- Add a **"Copy Chords + Lyrics"** button that exports as plain text in a guitar tab-friendly format

> ⚠️ **Whisper on Free Tier:** Whisper's `base` model needs ~250MB RAM. Render's free tier only has 512MB — this is tight. If it OOMs, use the `tiny` model (60MB, slightly less accurate). When ready to scale, upgrade Render to 1GB RAM ($7/mo) and use `small` for better accuracy.

---

## 6. Version 3 — Easy/Beginner Chords

### Approach

"Easy chords" means two things: (1) mapping detected chords to beginner-friendly equivalents, and (2) suggesting a capo position so the guitarist can play simpler chord shapes. This is **pure music theory** — no audio reprocessing needed.

### Capo Suggestion Algorithm

Given the detected key of the song, find the capo position (0–7 frets) where the resulting effective key uses only open chord shapes. The most guitar-friendly keys are C, G, D, A, and E major, and their relative minors (Am, Em, Dm, Bm).

For each capo position 0–7: calculate what key the guitar would effectively be in → score that key by how "easy" it is → return the capo position with the best score.

### Chord Simplification Rules

| Original Chord | Simplified To | Rule |
|----------------|--------------|------|
| Cmaj7, Cadd9, C6 | C | Strip extensions from major chords |
| Am7, Amsus2 | Am | Strip extensions from minor chords |
| Bm, F#m, C#m | Keep + flag as barre | These require barre — suggest capo to avoid |
| F | Fmaj7 (xx3210) or Capo 1 + E | Most notorious barre chord for beginners |
| Bb, Eb, Ab | Use capo to shift to A, D, G | Flat keys are unfriendly for open guitar |

> 📝 **Coding Agent Note — Easy Chords (v3)**
>
> Add an `easy_chords.py` module with two functions:
> - `suggest_capo(key: str) -> int` — returns optimal capo fret 0–7
> - `simplify_progression(chords: list[dict], capo: int) -> list[dict]` — applies capo transposition then strips extensions
>
> Add a **"Show Easy Chords"** toggle in the frontend that switches between original and simplified chords. Display the capo recommendation prominently when active.

---

## 7. Known Limitations & How to Handle Them

| Limitation | Impact | Mitigation |
|-----------|--------|-----------|
| Chord detection accuracy ~60–80% | Complex jazz/chromatic songs may be wrong | Works well on pop/rock with clear harmony. Set user expectations. |
| Struggles with distorted guitars | Heavy metal may produce noise | HPSS helps. Works best on acoustic/pop. |
| Render free tier cold starts (~50s) | First user after idle waits a long time | Show a "Server waking up…" message. Upgrade at scale. |
| Whisper memory usage | Can OOM on free tier | Use `tiny` model on free tier. Upgrade for `base`/`small`. |
| No user accounts in MVP | Results lost after Redis TTL (1hr) | Acceptable for MVP. Add Supabase auth + DB in v4 if needed. |

---

## 8. Testing Strategy

### Backend
- Unit test `transposer.py` with known inputs: C major up 2 semitones should yield D major
- Unit test `chord_detector.py` with a generated sine wave of a C major chord (440Hz + 523Hz + 659Hz) — should detect `'C'` with high confidence
- Integration test the full API: upload a sample WAV, poll until done, verify response shape

### Frontend
- Test `TransposeControl`: sliding to +2 should update all displayed chord names
- Test the polling hook: mock API responses to simulate `queued → processing → done` state transitions

### End-to-end test file
Keep a short 30-second test MP3 of a simple I–IV–V song (e.g. 4 bars of C–F–G–C) in the repo under `/test-assets/`. Use this as the canonical test case for all CI/CD pipeline runs.

---

## 9. Exact Implementation Order for Coding Agent

Follow this order strictly. Each step should be independently testable before moving to the next.

### Phase 1 — Backend Core *(do this first)*

1. Create `backend/` folder. Set up `requirements.txt` with librosa, fastapi, rq, redis.
2. Write `chord_detector.py`. **Test it locally with a sample WAV from the command line** before wiring to the API.
3. Write `transposer.py`. Quick test: `transpose_progression([{chord:'C'}], 2) == [{chord:'D'}]`.
4. Write `main.py` with `POST /api/analyze` and `GET /api/status/{job_id}`.
5. Write `worker.py` to launch the RQ worker.
6. Write `Dockerfile`. Build and run locally to confirm it works.
7. Set up Upstash Redis. Set up Render services. Deploy. Test the API directly with curl or Postman.

### Phase 2 — Frontend *(after backend is live)*

1. Create `frontend/` with `create-next-app`. Install `tailwindcss`, `@tanstack/react-query`, `axios`.
2. Build the upload page with drag-and-drop. Wire to backend.
3. Build the results page with polling. Show a loading state.
4. Build `ChordTimeline` using hardcoded test data first, then wire to real API response.
5. Build `TransposeControl`. Wire up the `transpose.ts` utility.
6. Deploy to Vercel. Set `NEXT_PUBLIC_API_URL`. Full end-to-end test.

### Phase 3 — Lyrics *(v2, after MVP ships)*

1. Add `faster-whisper` to `requirements.txt`. Update Dockerfile.
2. Write `lyrics_transcriber.py`. Test locally.
3. Update the worker job to run chord detection + lyrics detection together.
4. Update API response schema to include a `lyrics` field.
5. Build `LyricsDisplay` frontend component.
6. Add playback timeline sync using `audio.ontimeupdate`.

### Phase 4 — Easy Chords *(v3, after v2 ships)*

1. Write `easy_chords.py` with capo suggestion and chord simplification.
2. Add an optional `?easy_mode=true` query param or a frontend toggle.
3. Build the "Easy Mode" toggle in the frontend.
4. Display capo suggestion prominently in easy mode.

---

## 10. Quick Reference

### Key Python Libraries

| Library | Purpose |
|---------|---------|
| `librosa` | Audio loading, HPSS, chroma features, tempo detection |
| `numpy` / `scipy` | Math operations, median filter smoothing |
| `fastapi` / `uvicorn` | Async HTTP API server |
| `rq` | Simple Redis-backed job queue (lightweight Celery alternative) |
| `redis-py` | Python Redis client |
| `faster-whisper` | Fast Whisper ASR with word-level timestamps (v2+) |

### Key Frontend Libraries

| Library | Purpose |
|---------|---------|
| `Next.js 14` | React framework, App Router, free Vercel deploys |
| `@tanstack/react-query` | Data fetching, polling, caching |
| `tailwindcss` | Utility CSS styling |
| `axios` / `fetch` | HTTP client for API calls |

### Free Tier Cost Summary

| Service | Free Limit | What happens when exceeded |
|---------|-----------|---------------------------|
| Vercel (frontend) | 100GB bandwidth/mo | Upgrade to Pro ($20/mo) |
| Render (backend) | 750 hrs/mo compute | Upgrade to Starter ($7/mo) for always-on |
| Upstash Redis | 10k commands/day | Pay-per-use ($0.20 per 100k cmds) |
| Cloudflare R2 (v2+) | 10GB storage, 1M requests/mo | $0.015/GB/mo beyond free |
| **Total at launch** | **$0/month** | Up to a few hundred users/day is free |

---

*ChordLens Blueprint · v1.0 · React/Next.js + Python FastAPI · Progressive Roadmap (MVP → v3)*
