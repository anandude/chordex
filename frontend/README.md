# Chordex frontend

Next.js 16 app (App Router, Tailwind CSS 4, TanStack Query). It talks to the
FastAPI backend at `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`).

```bash
npm install
npm run dev        # http://localhost:3000 (start the backend too: ../start.sh does both)
npm run lint
npx tsc --noEmit
```

| Path | |
|---|---|
| `app/page.tsx` | Upload / YouTube link page |
| `app/results/[jobId]/page.tsx` | Results: control panel + chord sheet |
| `components/ChordSheet.tsx` | Renders the backend-built sheet (chords on syllables) |
| `lib/chordSheet.ts` | Sheet helpers: active row/word, ChordPro export |
| `lib/transpose.ts`, `lib/easyChords.ts` | Transpose and Easy Mode (client-side) |

See the [root README](../README.md) for the full setup.
