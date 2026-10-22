# Deploying Chordex

The live site is split in two. Local development (`./start.sh`) is unchanged.

| Part | Where | Config |
|---|---|---|
| Backend (API, worker, Redis) | InstaBox machine `chordex` (4 vCPU, 8 GB, CPU only) | this folder |
| Frontend (static) | Cloudflare Pages project `chordex` → https://chordex.pages.dev | `NEXT_PUBLIC_API_URL` at build |
| Frontend (alt) | Vercel project `chordex` → https://chordex-eta.vercel.app | Vercel env var |

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

## Frontend on Cloudflare Pages (free)

The site is fully client-side, so it ships as a static export. Every
`/results/<id>` is served by one page (`public/_redirects`), which reads the id
from the URL.

```bash
# From the repository root — the Next.js app lives there since it moved out of
# frontend/ (commit 97470d6).
NEXT_OUTPUT=export NEXT_PUBLIC_API_URL=https://8000-<id>.instabox.tech npx next build
npx wrangler pages deploy out --project-name chordex --branch main
```

Set the Pages project's **root directory** to the repository root. `public/_redirects`
must ship with the export — it is what makes `/results/<id>` resolve on the
static host, and the site 404s on every result link without it.

## Frontend on Vercel

Deploy from the repository root with `vercel deploy --prod` (`vercel.json` pins
the Next.js preset; `.vercelignore` keeps `.env.local` out). The Vercel
project's **Root Directory** setting must be the repository root, not
`frontend/`. Set
`NEXT_PUBLIC_API_URL` to the InstaBox URL (no trailing slash) for
Production, then redeploy: the value is baked in at build time. Put the Vercel
domain in the backend's `ALLOWED_ORIGINS` and run `docker compose up -d`.

## Things to know

- **Idle pause.** The machine pauses after 30 minutes idle. The next request
  wakes it and waits, so the first visit after a quiet spell is slow. A
  machine you paused by hand stays offline until you resume it.
- **Speed.** Chords and lyrics run on separate workers, so chords appear
  in ~30–40 s while lyrics continue. `LYRICS_DEMUCS_OVERLAP=0.1` makes
  separation ~30% faster; `LYRICS_ALIGN_INT8` is an opt-in ~5x faster
  aligner.
- **CPU only.** Chords take seconds. Lyrics that aren't on LRCLIB take a few
  minutes (Demucs and Whisper on 4 cores).
- **YouTube** often blocks cloud IPs. File uploads always work.
- **The API URL is public.** Anyone who has it can submit jobs.
- **Disk.** Uploaded audio is deleted after two hours by the `cleanup`
  service. Models live in the `hf_cache`, `torch_cache` and `ct2_models` volumes.
