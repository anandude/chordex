# Deploying Chordex

The live site is split in two. Local development (`./start.sh`) is unchanged.

| Part | Where | Config |
|---|---|---|
| Backend (API, worker, Redis) | InstaBox machine `chordex` (4 vCPU, 8 GB, CPU only) | this folder |
| Frontend (Next.js) | Vercel project `chordex` → https://chordex-eta.vercel.app | `NEXT_PUBLIC_API_URL` |

## Backend on InstaBox

```bash
instabox ssh chordex
git clone https://github.com/anandude/chordex.git && cd chordex/deploy/instabox
cp .env.example .env          # set ALLOWED_ORIGINS (and HF_TOKEN for Malayalam)
docker compose up -d --build
docker compose exec worker python prewarm.py --all   # download models now
instabox-port publish 8000 --name 'Chordex API'  # prints the public URL
```

Check it with `curl https://8000-<id>.<domain>/health`.

Update to the latest code:

```bash
cd ~/chordex && git pull && cd deploy/instabox && docker compose up -d --build
```

Logs: `docker compose logs -f worker`.

## Frontend on Vercel

Deploy from `frontend/` with `vercel deploy --prod` (`vercel.json` pins the
Next.js preset; `.vercelignore` keeps `.env.local` out). Set
`NEXT_PUBLIC_API_URL` to the InstaBox URL (no trailing slash) for
Production, then redeploy: the value is baked in at build time. Put the Vercel
domain in the backend's `ALLOWED_ORIGINS` and run `docker compose up -d`.

## Things to know

- **Idle pause.** The machine pauses after 30 minutes idle. The next request
  wakes it and waits, so the first visit after a quiet spell is slow. A
  machine you paused by hand stays offline until you resume it.
- **CPU only.** Chords take seconds. Lyrics that aren't on LRCLIB take a few
  minutes (Demucs and Whisper on 4 cores).
- **YouTube** often blocks cloud IPs. File uploads always work.
- **The API URL is public.** Anyone who has it can submit jobs.
- **Disk.** Uploaded audio is deleted after two hours by the `cleanup`
  service. Models live in the `hf_cache`, `torch_cache` and `ct2_models` volumes.
