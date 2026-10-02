#!/usr/bin/env python3
"""Phase 6 — data-collection script (design phase: builds training pairs, trains nothing).

Semi-automatic (audio_segment, text) pairs for singing-adapted ASR:
songs with LRCLIB synced lyrics → vocal separation → segment audio by LRC
line timestamps → filter (duration, vocal energy, alignment confidence) →
emit pairs + a manifest.

Usage:
    python eval/collect_pairs.py --songs song1.mp3 song2.mp3 --out eval/pairs \
        --title "Song" --artist "Singer" --language ml

Output: <out>/<song>/<i>.wav + manifest.jsonl {audio, text, language,
duration, rms_db, align_conf, source}. Audio is derived from YOUR files —
never commit it; the dataset is reproducible from links, not shipped.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

MIN_DUR, MAX_DUR = 2.0, 15.0
MIN_RMS_DB = -35.0
MIN_ALIGN_CONF = 0.4


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 6 training-pair collector")
    ap.add_argument("--songs", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default=None)
    ap.add_argument("--artist", default=None)
    ap.add_argument("--language", default="ml", choices=["hi", "ml"])
    ap.add_argument("--separation", default="demucs", choices=["none", "demucs", "roformer"])
    args = ap.parse_args()

    import librosa
    import numpy as np
    import soundfile as sf

    from pipeline.alignment import align
    from pipeline.config import LyricsConfig
    from pipeline.lyrics_lookup import lookup_lyrics
    from pipeline.separation import separate_vocals

    cfg = LyricsConfig(separation_backend=args.separation)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest = open(out / "manifest.jsonl", "a", encoding="utf-8")
    kept = dropped = 0

    for song in args.songs:
        audio = Path(song)
        hit = lookup_lyrics(audio, title=args.title, artist=args.artist, cfg=cfg)
        if not hit:
            print(f"[{audio.name}] no LRCLIB hit — skipped")
            continue
        stem = separate_vocals(audio, cfg=cfg)
        y, sr = librosa.load(str(stem), sr=16000, mono=True)
        al = align(stem, lines=hit["lines"], language=args.language, cfg=cfg)
        conf_by_word = {i: w.get("confidence", 0.0) for i, w in enumerate(al["words"])}
        wi = 0
        for li, line in enumerate(hit["lines"]):
            toks = line["text"].split()
            seg_words = al["words"][wi:wi + len(toks)]
            wi += len(toks)
            s = line["timestamp"]
            e = line.get("end", s + 4.0)
            dur = e - s
            if not (MIN_DUR <= dur <= MAX_DUR):
                dropped += 1
                continue
            seg = y[int(s * sr):int(e * sr)]
            rms_db = float(20 * np.log10(np.sqrt(np.mean(seg ** 2)) + 1e-9))
            if rms_db < MIN_RMS_DB:
                dropped += 1
                continue
            conf = sum(conf_by_word.get(i, 0.0) for i in range(wi - len(toks), wi)) / max(1, len(toks))
            if conf < MIN_ALIGN_CONF:
                dropped += 1
                continue
            d = out / f"{audio.stem}_{li:03d}.wav"
            sf.write(str(d), seg, 16000)
            manifest.write(json.dumps({"audio": str(d), "text": line["text"],
                                       "language": args.language, "duration": round(dur, 2),
                                       "rms_db": round(rms_db, 1),
                                       "align_conf": round(conf, 2),
                                       "source": hit["source"]}, ensure_ascii=False) + "\n")
            kept += 1
    manifest.close()
    print(f"kept={kept} dropped={dropped} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
