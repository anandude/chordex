# Contributing to Chordex

Thanks for helping! Chordex turns a song into a playable chord sheet: chords,
lyrics, and each chord placed on the syllable where it changes. Contributions
of all sizes are welcome, from typo fixes to new language support.

## Ways to help

- **Try it on your music** and [open an issue](../../issues/new/choose) when
  chords or lyrics come out wrong. Include the song name, language and what
  you expected. Please don't attach copyrighted audio. A YouTube link is fine.
- **Romanisation spelling.** If a Hindi/Malayalam/Tamil word comes out in an
  unnatural English spelling, add it as a case in
  `backend/tests/test_romanise.py` and fix the rule in
  `backend/pipeline/romanise.py`.
- **More languages.** Tamil, Telugu, Kannada, Bengali and others work, but
  only Hindi and Malayalam have tuned models and spelling rules.
- **Accuracy references.** The eval harness (`eval/`) can score lyrics and
  chord placement, but only for songs with hand-made reference files. See
  `eval/refs/REFERENCES.md`.
- Issues labelled
  [`good first issue`](../../issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
  are a good place to start.

## Development setup

See the [README](README.md#quick-start). In short:

```bash
git clone https://github.com/anandude/chordex.git && cd chordex
./start.sh            # first run creates backend/.venv and installs everything
```

A GPU is optional. Everything runs on CPU, just more slowly.

## Before you open a pull request

```bash
# backend
cd backend && .venv/bin/python -m pytest -q

# frontend
cd frontend && npm run lint && npx tsc --noEmit
```

CI runs the same checks on every pull request.

- **Keep PRs focused**: one change per PR, with a description of what and why.
- **Add tests** for backend logic. Chord↔lyric placement (`pipeline/sheet.py`)
  and romanisation already have good coverage; please keep it that way.
- **Measure, don't guess**: for changes that claim better speed or accuracy,
  include before/after numbers from `eval/run_eval.py` (it appends to
  `eval/timing.md`).
- **Match the surrounding style**: comment density, naming and idioms.
- **Don't** commit audio files, model weights, `.env` files, or licensed
  fonts/icons/images. The `.gitignore` blocks the common cases.

## Project layout

| Path | What lives there |
|---|---|
| `backend/main.py` | FastAPI app: upload / YouTube link → jobs → status + sheet |
| `backend/worker.py` | RQ worker: `chord_jobs` (fast) and `lyrics_jobs` (slow) |
| `backend/chord_engine/` | Chordino + template-HMM chord recognition |
| `backend/pipeline/` | Lyrics: separation → ASR → forced alignment → sheet, plus romanisation |
| `backend/youtube.py` | YouTube audio fetcher (yt-dlp) |
| `frontend/app/` | Next.js pages (upload, results) |
| `frontend/components/` | Player, chord sheet, transpose / Easy Mode controls |
| `eval/` | Benchmark + accuracy harness |
| `docs/` | Design notes and plans |

## Licensing of contributions

By contributing you agree that your contributions are licensed under the
project's [MIT license](LICENSE). If you add a dependency, model or asset,
note its license in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). Be kind.
