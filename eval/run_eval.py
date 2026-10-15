#!/usr/bin/env python3
"""Offline end-to-end benchmark — the worker pipeline without Redis/RQ.

Reproduces what a real upload goes through: the song is copied to
``<tmp>/<job>/audio.<ext>`` (exactly how storage.save_upload stores it), then
the chord job and the lyrics job run on it. Every run uses a FRESH lyrics
cache dir unless --warm is passed, so stage timings are cold and honest.

Usage (from repo root):
    backend/.venv/bin/python eval/run_eval.py --tag baseline
    backend/.venv/bin/python eval/run_eval.py --tag s1 --only hi_chahun
    backend/.venv/bin/python eval/run_eval.py --tag x --backend /path/to/other/backend

Outputs:
    eval/runs/<tag>/<song>.json   full output (lyrics text → gitignored)
    eval/timing.md                one appended row per song (committed)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "eval"


def _metrics(song: dict, out: dict) -> dict:
    """Accuracy metrics where references exist; None = not measurable."""
    sys.path.insert(0, str(EVAL))
    from score import cer, is_placeholder_ref, wer  # noqa: E402

    m: dict = {"cer": None, "wer": None, "placement": None, "onset_mae_ms": None}
    ref_path = ROOT / song.get("ref_lyrics", "")
    if song.get("ref_lyrics") and ref_path.is_file():
        ref = ref_path.read_text(encoding="utf-8")
        if not is_placeholder_ref(ref):
            hyp = "\n".join(l.get("text", "") for l in out["lyrics"].get("lines", []))
            m["cer"], m["wer"] = round(cer(ref, hyp), 4), round(wer(ref, hyp), 4)
    try:
        from score_placement import onset_mae_ms, placement_accuracy

        cho = ROOT / song.get("ref_chordpro", "")
        if song.get("ref_chordpro") and cho.is_file() and out.get("sheet"):
            m["placement"] = placement_accuracy(
                cho.read_text(encoding="utf-8"), out["sheet"], out["chords"]["chords"]
            )
        ons = ROOT / song.get("ref_onsets", "")
        if song.get("ref_onsets") and ons.is_file():
            m["onset_mae_ms"] = onset_mae_ms(
                ons.read_text(encoding="utf-8"), out["lyrics"].get("lyrics", [])
            )
    except ImportError:
        pass
    return m


def run_song(song: dict, args: argparse.Namespace, cache_dir: Path) -> dict:
    src = ROOT / song["audio"]
    job_dir = Path(tempfile.mkdtemp(prefix="chordex_eval_")) / "job"
    job_dir.mkdir(parents=True)
    audio = job_dir / f"audio{src.suffix.lower()}"
    shutil.copyfile(src, audio)

    os.environ["LYRICS_CACHE_DIR"] = str(cache_dir)
    from chord_detector import detect_chords
    from lyrics_transcriber import transcribe_lyrics

    t0 = time.time()
    chords = detect_chords(str(audio))
    chord_wall = round(time.time() - t0, 2)

    kwargs: dict = {"duration": chords.get("duration")}
    if args.lang_hint:
        kwargs["language"] = song.get("language")
    # Newer pipelines accept the original upload filename (S2); older ones don't.
    import inspect

    if "filename" in inspect.signature(transcribe_lyrics).parameters:
        kwargs["filename"] = src.name
    t0 = time.time()
    lyrics = transcribe_lyrics(str(audio), **kwargs)
    lyrics_wall = round(time.time() - t0, 2)

    sheet = None
    try:
        from pipeline.sheet import build_sheet

        sheet = build_sheet(
            chords.get("chords", []), lyrics.get("lyrics", []), lyrics.get("lines", []),
            beats=chords.get("beats"), tempo=chords.get("tempo"),
        )
    except ImportError:
        pass

    shutil.rmtree(job_dir.parent, ignore_errors=True)
    return {
        "song": song["id"], "chord_wall_s": chord_wall, "lyrics_wall_s": lyrics_wall,
        "chords": chords, "lyrics": lyrics, "sheet": sheet,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--bench", default=str(EVAL / "bench.json"))
    ap.add_argument("--only", action="append", help="song id(s) to run")
    ap.add_argument("--backend", default=str(ROOT / "backend"))
    ap.add_argument("--lang-hint", action="store_true",
                    help="pass the manifest language (default: auto, like the UI default)")
    ap.add_argument("--warm", action="store_true", help="reuse eval/cache (stage cache hits)")
    ap.add_argument("--note", default="")
    args = ap.parse_args()

    sys.path.insert(0, args.backend)
    os.chdir(args.backend)
    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")

    bench = json.loads(Path(args.bench).read_text(encoding="utf-8"))
    songs = [s for s in bench["songs"] if not args.only or s["id"] in args.only]
    out_dir = EVAL / "runs" / args.tag
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = EVAL / "cache" if args.warm else Path(tempfile.mkdtemp(prefix="chordex_evalcache_"))

    timing = EVAL / "timing.md"
    if not timing.exists():
        timing.write_text(
            "# Pipeline timing + accuracy (append-only)\n\n"
            "Cold cache unless noted. `stages` = lyrics stage seconds. Accuracy columns are "
            "`-` when the reference is missing (not measurable).\n\n"
            "| date | tag | song | chords s | lyrics s | stages | lang | source | asr model | align | words | CER | WER | placement | onset MAE ms | note |\n"
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n",
            encoding="utf-8",
        )
    for song in songs:
        res = run_song(song, args, cache_dir)
        res["metrics"] = _metrics(song, res)
        (out_dir / f"{song['id']}.json").write_text(
            json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        ly = res["lyrics"]
        fmt = lambda v: "-" if v is None else v  # noqa: E731
        stages = ", ".join(f"{k} {v}" for k, v in (ly.get("stages") or {}).items())
        row = (
            f"| {time.strftime('%Y-%m-%d')} | {args.tag} | {song['id']} | {res['chord_wall_s']} | "
            f"{res['lyrics_wall_s']} | {stages} | {ly.get('language')} | {ly.get('source')} | "
            f"{(ly.get('models') or {}).get('asr', '-')} | {(ly.get('models') or {}).get('alignment', '-')} | "
            f"{len(ly.get('lyrics') or [])} | {fmt(res['metrics']['cer'])} | {fmt(res['metrics']['wer'])} | "
            f"{fmt(res['metrics']['placement'])} | {fmt(res['metrics']['onset_mae_ms'])} | {args.note} |\n"
        )
        with timing.open("a", encoding="utf-8") as f:
            f.write(row)
        print(row, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
