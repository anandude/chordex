# ChordLens (Chordex) — Guitar Chord Analyzer

Upload any MP3 or WAV → get a timestamped chord progression → transpose to any key → play along with the audio.

**Stack:** Next.js 16 + Python FastAPI · **Queue:** Redis + RQ · **Engines:** Chordino (primary) / improved template+HMM (fallback)

---

## What's new (v2 engine)

| Before | After |
|--------|--------|
| Krumhansl key-profile templates (maj/min only) | **Chordino** (NNLS-chroma, large vocab) when available |
| No sequence model | **HMM Viterbi** fallback engine with maj/min/7/sus/dim/… |
| Hard `/tmp` handoff (breaks multi-service) | Shared `UPLOAD_DIR` + optional S3/R2 |
| Chords only | **Key estimate**, confidence, **audio playback** + playhead sync |

---

## Project structure

```
Chordex/
  backend/
    chord_detector.py       Facade → chord_engine
    chord_engine/           Chordino + template-HMM engines
    postprocess.py          Merge, beat-snap, key, tempo
    label_map.py            MIREX/Harte → guitar labels
    storage.py              Local / S3 upload storage
    main.py                 FastAPI
    worker.py               RQ worker
    transposer.py
  frontend/                 Next.js app
  docker-compose.yml        Redis + API + worker
  test-assets/              Synthetic WAVs
```

---

## Local development

### Prerequisites

- Python 3.11+
- Node.js 18+
- Docker (used for Redis — no local `redis-server` install needed)
- `ffmpeg` + `libsndfile1` (Ubuntu: `sudo apt-get install -y ffmpeg libsndfile1`)

### One command (recommended)

From the project root:

```bash
./start.sh
```

That starts **Redis + API + worker + frontend** and opens:

| Service  | URL |
|----------|-----|
| App      | http://localhost:3000 |
| API      | http://localhost:8000 |
| Health   | http://localhost:8000/health |

| Command | What it does |
|---------|----------------|
| `./start.sh` | Run everything (installs missing deps on first run) |
| `./start.sh --setup` | Force reinstall/setup, then start |
| `./start.sh --stop` | Stop all processes / Redis container |
| `./start.sh --docker` | API + worker + Redis via Docker Compose only |

Logs: `.run/logs/api.log`, `worker.log`, `frontend.log`  
Stop: **Ctrl+C** or `./start.sh --stop`

### Manual / advanced

```bash
# Backend only
cd backend && source .venv/bin/activate && bash install_deps.sh
uvicorn main:app --reload --port 8000   # terminal 1
python worker.py                        # terminal 2

# Frontend only
cd frontend && npm install && npm run dev
```

```bash
curl -F "file=@test-assets/c_f_g_c.wav" http://localhost:8000/api/analyze
curl http://localhost:8000/api/status/<job_id>
```

### Engine selection

| `CHORD_ENGINE` | Behavior |
|----------------|----------|
| `auto` (default) | Chordino if install works, else template-HMM |
| `chordino` | Chordino only (error if unavailable) |
| `template` | Improved template + HMM only |

---

## Tests

```bash
cd backend
source .venv/bin/activate
pytest -q

# Generate synthetic fixtures (optional)
python ../test-assets/generate_fixtures.py
```

---

## Deployment notes

1. **API + worker must share audio storage** — use the same `UPLOAD_DIR` volume, or set `S3_BUCKET` (+ endpoint for R2).
2. Render: two services from the same Docker image (`uvicorn` and `python worker.py`).
3. Vercel frontend: `NEXT_PUBLIC_API_URL` → your API URL.
4. Cold starts on free tiers can take ~50s; the UI already shows a wake-up message.

---

## Roadmap

| Version | Feature | Status |
|---------|---------|--------|
| **MVP** | Upload → chords → transpose | Done |
| **v2 engine** | Chordino / HMM, key, playback | Done |
| **v3** | Capo + beginner easy chords | Planned |
| **Later** | Lyrics (Whisper) | Planned |

---

## Honest accuracy note

Automatic chord recognition on mixed commercial audio is **not 100%**. Open systems typically land ~70–80% maj/min on pop benchmarks. ChordLens aims for **playable progressions** on clear pop/rock/acoustic tracks; trust your ear on dense metal/jazz.
