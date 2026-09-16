#!/usr/bin/env python3
"""Phase 0 evaluation harness — Indic lyrics transcription.

Scores hypothesis transcripts against hand-verified refs and appends one
aggregate row per run to eval/results.md.

Usage:
    # Run the current pipeline on every manifest song that has audio + a real ref
    python eval/score.py --config baseline

    # Score pre-generated hypothesis .txt files (one per song_id) instead
    python eval/score.py --config demucs --hyp-dir eval/hyps/demucs

    # Validate manifest coverage without running any model
    python eval/score.py --check

    # Smoke-test the pipeline import + timing on a synthetic fixture (no ref needed)
    python eval/score.py --smoke

Normalizer (minimal, documented — NOT Whisper's normalizer, which is broken
for Malayalam and flatters numbers):
    1. Unicode NFC normalisation (canonical composition of Indic matras).
    2. Remove punctuation/symbols: keep characters whose Unicode category
       starts with L (letters), M (combining marks — Indic vowel signs /
       matras live here and MUST be kept), or N (numbers), plus Zs (space).
       Everything else (danda U+0964, commas, quotes, LRC timestamps) is
       replaced with a space. No stop-word removal, no stemming.
    3. Collapse all whitespace runs to single spaces, strip ends.
    4. Lowercase ASCII A-Z only. Indic scripts have no case and are untouched;
       Latin code-mixed tokens (e.g. "Love") are lowercased so "Love"/"love"
       do not count as errors.

Metrics (pure stdlib, no jiwer dependency):
    CER = char-level Levenshtein(ref, hyp) / max(1, len(ref chars))
    WER = word-level Levenshtein(ref words, hyp words) / max(1, len(ref words))
    Both computed AFTER the normalizer above. CER is the primary metric
    (Malayalam agglutination makes WER disproportionately punishing).
    Aggregates are the arithmetic mean of per-song rates, reported SEPARATELY
    per language. Hindi and Malayalam are never averaged together.

Manifest refs that still contain the 'TODO' placeholder are treated as
missing — scoring them would produce garbage numbers, so those songs are
skipped with a warning.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EVAL = Path(__file__).resolve().parent
MANIFEST = EVAL / "manifest.json"
RESULTS = EVAL / "results.md"
PLACEHOLDER = "TODO"


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text or "")
    chars: list[str] = []
    for ch in text:
        cat = unicodedata.category(ch)
        if cat[0] in ("L", "M", "N") or cat == "Zs":
            chars.append(ch)
        elif ch in (" ", "\t", "\n", "\r"):
            chars.append(" ")
        else:
            chars.append(" ")  # punctuation / symbols -> space
    text = "".join(chars)
    text = re.sub(r"\s+", " ", text).strip()
    # Lowercase Latin only — .lower() on Indic text is a no-op anyway, but be explicit.
    text = "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in text)
    return text


def levenshtein(a: list, b: list) -> int:
    """Edit distance over any sequence (chars as 1-elem lists, or word lists)."""
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[-1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(ref: str, hyp: str) -> float:
    r, h = normalize(ref), normalize(hyp)
    if not r:
        return 0.0 if not h else 1.0
    return levenshtein(list(r), list(h)) / max(1, len(r))


def wer(ref: str, hyp: str) -> float:
    r, h = normalize(ref).split(), normalize(hyp).split()
    if not r:
        return 0.0 if not h else 1.0
    return levenshtein(r, h) / max(1, len(r))


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def is_placeholder_ref(text: str) -> bool:
    return PLACEHOLDER in text[:200]


def check_manifest(manifest: dict, base: Path = EVAL) -> tuple[bool, list[str]]:
    """Validate the 12-song coverage contract. Returns (ok, messages)."""
    problems: list[str] = []
    songs = manifest.get("songs", [])
    hi = [s for s in songs if s.get("language") == "hi"]
    ml = [s for s in songs if s.get("language") == "ml"]
    if len(hi) < 6:
        problems.append(f"hindi songs: {len(hi)} < 6")
    if len(ml) < 6:
        problems.append(f"malayalam songs: {len(ml)} < 6")
    for lang, group in (("hi", hi), ("ml", ml)):
        eras = {s["attributes"]["era"] for s in group if "attributes" in s}
        vocals = {s["attributes"]["vocal"] for s in group if "attributes" in s}
        prods = {s["attributes"]["production"] for s in group if "attributes" in s}
        if not {"modern", "older"} <= eras:
            problems.append(f"{lang}: need modern + older, have {sorted(eras)}")
        if not {"female", "male"} <= vocals:
            problems.append(f"{lang}: need female + male lead, have {sorted(vocals)}")
        if not {"dense", "sparse"} <= prods:
            problems.append(f"{lang}: need dense + sparse, have {sorted(prods)}")
    if sum(1 for s in songs if s.get("attributes", {}).get("reverb") == "heavy") < 2:
        problems.append("need >= 2 heavy-reverb tracks across set")
    if sum(1 for s in songs if s.get("attributes", {}).get("code_mix")) < 1:
        problems.append("need >= 1 code-mixed track")
    ready = sum(
        1
        for s in songs
        if s.get("audio")
        and (base / str(s["audio"])).exists()
        and (base / str(s.get("ref", ""))).exists()
        and PLACEHOLDER
        not in (base / str(s.get("ref", ""))).read_text(encoding="utf-8")[:200]
    )
    return (not problems, problems + [f"ready to score: {ready}/{len(songs)}"])


def transcribe_current_pipeline(audio_path: Path, language: str) -> tuple[str, float]:
    """Run the repo's untouched lyrics pipeline. Returns (hyp_text, seconds)."""
    sys.path.insert(0, str(REPO / "backend"))
    from lyrics_transcriber import transcribe_lyrics  # noqa: E402

    lang_hint = {"hi": "hi", "ml": "ml"}.get(language)
    t0 = time.time()
    out = transcribe_lyrics(str(audio_path), language=lang_hint)
    dt = time.time() - t0
    words = out.get("lyrics") or []
    if words:
        hyp = " ".join(w.get("word", "") for w in words)
    else:
        hyp = " ".join(line.get("text", "") for line in out.get("lines", []))
    if out.get("error"):
        print(f"    [lyrics_error] {out['error']}", flush=True)
    return hyp, dt


def score_pair(ref: str, hyp: str) -> dict:
    return {
        "cer": round(cer(ref, hyp), 4),
        "wer": round(wer(ref, hyp), 4),
        "ref_chars": len(normalize(ref)),
        "hyp_chars": len(normalize(hyp)),
    }


def ensure_results_header() -> None:
    if RESULTS.exists():
        return
    RESULTS.write_text(
        "# Lyrics eval results (append-only)\n\n"
        "One row per config. CER is primary (esp. Malayalam); WER secondary. "
        "Hindi and Malayalam are never averaged. Normalizer: NFC, strip "
        "punctuation, collapse whitespace, lowercase Latin only "
        "(see `eval/score.py::normalize`).\n\n"
        "| date | config | n_hi | hi_CER | hi_WER | n_ml | ml_CER | ml_WER |"
        " sec/song | notes |\n"
        "|---|---|---|---|---|---|---|---|---|---|\n",
        encoding="utf-8",
    )


def append_row(config: str, per_lang: dict, sec_per_song: float | None, notes: str) -> None:
    ensure_results_header()
    hi = per_lang.get("hi", {"n": 0, "cer": "-", "wer": "-"})
    ml = per_lang.get("ml", {"n": 0, "cer": "-", "wer": "-"})
    secs = f"{sec_per_song:.1f}" if sec_per_song is not None else "-"
    row = (
        f"| {date.today().isoformat()} | {config} | {hi['n']} | {hi['cer']} |"
        f" {hi['wer']} | {ml['n']} | {ml['cer']} | {ml['wer']} | {secs} | {notes} |\n"
    )
    with RESULTS.open("a", encoding="utf-8") as f:
        f.write(row)


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 0 lyrics eval harness")
    ap.add_argument("--config", default="baseline", help="config name for results.md row")
    ap.add_argument("--manifest", default=str(MANIFEST))
    ap.add_argument("--hyp-dir", default=None, help="score existing <song_id>.txt hyps instead of running ASR")
    ap.add_argument("--notes", default="", help="extra notes for the results row")
    ap.add_argument("--check", action="store_true", help="validate manifest only")
    ap.add_argument("--smoke", action="store_true", help="pipeline import + timing smoke test on synthetic fixture")
    ap.add_argument("--no-append", action="store_true", help="print scores without writing results.md")
    args = ap.parse_args()

    manifest_path = Path(args.manifest)
    manifest = load_manifest(manifest_path)
    base = manifest_path.parent  # refs/audio resolve relative to the manifest

    if args.check:
        ok, messages = check_manifest(manifest, base)
        print("manifest check:", "OK" if ok else "ISSUES")
        for m in messages:
            print(f"  - {m}")
        return 0 if ok else 1

    if args.smoke:
        fixture = REPO / "test-assets" / "c_major.wav"
        hyp, dt = transcribe_current_pipeline(fixture, "hi")
        print(f"smoke: transcribed {fixture.name} in {dt:.1f}s, hyp_chars={len(hyp)}")
        print(f"smoke: hyp={hyp[:120]!r}")
        return 0

    hyp_dir = Path(args.hyp_dir) if args.hyp_dir else (EVAL / "hyps" / args.config)
    hyp_dir.mkdir(parents=True, exist_ok=True)

    per_song: list[dict] = []
    skipped: list[str] = []
    total_time = 0.0
    timed = 0

    for song in manifest["songs"]:
        sid = song["song_id"]
        lang = song["language"]
        ref_path = base / song["ref"]
        if not ref_path.exists() or is_placeholder_ref(
            ref_path.read_text(encoding="utf-8", errors="replace")
        ):
            skipped.append(f"{sid} (ref placeholder)")
            continue
        ref = ref_path.read_text(encoding="utf-8")

        hyp_file = hyp_dir / f"{sid}.txt" if args.hyp_dir else None
        if hyp_file and hyp_file.exists():
            hyp = hyp_file.read_text(encoding="utf-8")
            dt = None
        elif args.hyp_dir:
            skipped.append(f"{sid} (no hyp in {args.hyp_dir})")
            continue
        else:
            audio_rel = song.get("audio")
            audio_path = (base / audio_rel) if audio_rel else None
            if not audio_path or not audio_path.exists():
                skipped.append(f"{sid} (audio missing)")
                continue
            print(f"[{sid}/{lang}] transcribing {audio_path.name} ...", flush=True)
            hyp, dt = transcribe_current_pipeline(audio_path, lang)
            (hyp_dir / f"{sid}.txt").write_text(hyp, encoding="utf-8")
            total_time += dt
            timed += 1

        s = score_pair(ref, hyp)
        s.update({"song_id": sid, "language": lang})
        if dt is not None:
            s["seconds"] = round(dt, 1)
        per_song.append(s)
        print(f"  {sid} [{lang}] CER={s['cer']:.4f} WER={s['wer']:.4f} (ref {s['ref_chars']}ch)")

    per_lang: dict = {}
    for lang in ("hi", "ml"):
        group = [s for s in per_song if s["language"] == lang]
        if group:
            per_lang[lang] = {
                "n": len(group),
                "cer": round(sum(s["cer"] for s in group) / len(group), 4),
                "wer": round(sum(s["wer"] for s in group) / len(group), 4),
            }
        else:
            per_lang[lang] = {"n": 0, "cer": "-", "wer": "-"}
    sec_per_song = (total_time / timed) if timed else None

    print(f"\nAggregate ({args.config}):")
    for lang in ("hi", "ml"):
        g = per_lang[lang]
        print(f"  {lang}: n={g['n']} CER={g['cer']} WER={g['wer']}")
    if sec_per_song is not None:
        print(f"  wall-clock: {sec_per_song:.1f}s/song over {timed} songs")
    if skipped:
        print(f"  skipped ({len(skipped)}): {', '.join(skipped)}")

    if not args.no_append:
        if per_song:
            notes = args.notes or f"{args.config} on {len(per_song)} songs"
        else:
            notes = args.notes or (
                "harness validated; 0/12 songs scored — audio + hand-verified"
                " refs pending from owner (see manifest.json)"
            )
        append_row(args.config, per_lang, sec_per_song, notes)
        print(f"appended row to {RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
