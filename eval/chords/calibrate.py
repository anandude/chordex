#!/usr/bin/env python3
"""calibrate.py — confidence calibration for chord engines (A3.3).

Answers two questions with numbers instead of vibes:
  1. Are the confidences honest?  (reliability diagram + Expected Calibration
     Error over 10 confidence bins)
  2. Is the N-threshold right?    (sweep 0.05–0.30, report frame accuracy +
     segment count per threshold; current template default is 0.12)

Correctness is majmin-equivalence per frame (10 Hz expansion): same root and
same major/minor family counts as correct; dim/aug/sus need exact matches;
N == N is correct. This mirrors the harness's primary gate (majmin) without
needing mir_eval, so calibration runs anywhere.

Usage:
  python calibrate.py --manifest manifest.json --hyps-dir hyps --tag template
  python calibrate.py --self-test   # dependency-free checks (numpy only)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from score_chords import load_lab, to_harte  # noqa: E402

FPS = 10.0
MIN_FAMILY = {"min", "min7"}
MAJ_FAMILY = {"maj", "7", "maj7"}


def _split_harte(label: str) -> tuple[str, str]:
    if label == "N":
        return "N", ""
    root, _, quality = label.partition(":")
    return root, quality or "maj"


def majmin_equal(hyp: str, ref: str) -> bool:
    """Lenient correctness: same root + same major/minor family."""
    hyp = to_harte(hyp)
    ref = to_harte(ref)
    if hyp == "N" or ref == "N":
        return hyp == ref
    hr, hq = _split_harte(hyp)
    rr, rq = _split_harte(ref)
    if hr != rr:
        return False
    if hq in MIN_FAMILY or rq in MIN_FAMILY:
        return hq in MIN_FAMILY and rq in MIN_FAMILY
    if hq in MAJ_FAMILY or rq in MAJ_FAMILY:
        return hq in MAJ_FAMILY and rq in MAJ_FAMILY
    return hq == rq


def load_hyp_conf(path: Path) -> tuple[np.ndarray, list[str], np.ndarray]:
    """Chordex result JSON -> (intervals, Harte labels, confidences)."""
    data = json.loads(Path(path).read_text())
    chords = data.get("chords", [])
    duration = data.get("duration")
    intervals, labels, confs = [], [], []
    for i, c in enumerate(chords):
        start = float(c["timestamp"])
        if c.get("end") is not None:
            end = float(c["end"])
        elif i + 1 < len(chords):
            end = float(chords[i + 1]["timestamp"])
        elif duration is not None:
            end = float(duration)
        else:
            end = start + 2.0
        if end <= start:
            continue
        intervals.append([start, end])
        labels.append(to_harte(c.get("chord", "N")))
        confs.append(float(c.get("confidence", 1.0)))
    if not intervals:
        raise ValueError(f"{path}: no chord events found")
    return np.asarray(intervals, dtype=float), labels, np.asarray(confs, dtype=float)


def apply_threshold(labels: list[str], confs: np.ndarray, t: float) -> list[str]:
    """Low-confidence segments become N (mirrors template_engine.py:156)."""
    return ["N" if c < t else l for l, c in zip(labels, confs)]


def expand_frames(ref_iv, ref_lb, est_iv, est_lb, est_conf, fps: float = FPS):
    """Per-frame (correct: bool, conf: float) arrays over the ref duration."""
    ref_end = float(ref_iv[-1, 1])
    n = max(1, int(round(ref_end * fps)))
    times = (np.arange(n) + 0.5) / fps
    ref_idx = np.clip(np.searchsorted(ref_iv[:, 1], times, side="right"), 0, len(ref_lb) - 1)
    est_idx = np.clip(np.searchsorted(est_iv[:, 1], times, side="right"), 0, len(est_lb) - 1)
    correct = np.array(
        [majmin_equal(est_lb[i], ref_lb[j]) for i, j in zip(est_idx, ref_idx)],
        dtype=bool,
    )
    return correct, np.asarray([est_conf[i] for i in est_idx], dtype=float)


def reliability(correct: np.ndarray, conf: np.ndarray, n_bins: int = 10) -> dict:
    """10-bin reliability table + ECE. Empty bins report None (not zero)."""
    bins = []
    ece = 0.0
    total = len(correct)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    for b in range(n_bins):
        lo, hi = edges[b], edges[b + 1]
        mask = (conf > lo) & (conf <= hi) if b else (conf >= lo) & (conf <= hi)
        cnt = int(mask.sum())
        if not cnt:
            bins.append({"bin": f"({lo:.1f},{hi:.1f}]", "n": 0,
                         "mean_conf": None, "accuracy": None})
            continue
        mean_c = float(conf[mask].mean())
        acc = float(correct[mask].mean())
        ece += abs(acc - mean_c) * (cnt / total)
        bins.append({"bin": f"({lo:.1f},{hi:.1f}]", "n": cnt,
                     "mean_conf": round(mean_c, 3), "accuracy": round(acc, 3)})
    return {"bins": bins, "ece": round(ece, 4), "n_frames": total,
            "accuracy": round(float(correct.mean()), 4)}


def self_test() -> int:
    failures = 0

    def check(name: str, cond: bool) -> None:
        nonlocal failures
        if not cond:
            print(f"FAIL {name}")
            failures += 1

    # majmin equivalence rules
    check("maj==7", majmin_equal("C:7", "C:maj"))
    check("maj7==maj", majmin_equal("C:maj7", "C:maj"))
    check("min==min7", majmin_equal("A:min7", "A:min"))
    check("maj!=min", not majmin_equal("C:maj", "C:min"))
    check("rel-maj!=rel-min", not majmin_equal("C:maj", "A:min"))
    check("root-matters", not majmin_equal("G:7", "C:maj"))
    check("sus-exact", majmin_equal("D:sus4", "D:sus4"))
    check("sus-not-maj", not majmin_equal("D:sus4", "D:maj"))
    check("dim-exact", majmin_equal("B:dim", "B:dim"))
    check("N==N", majmin_equal("N", "N"))
    check("N!=chord", not majmin_equal("N", "C:maj"))
    check("guitar-labels", majmin_equal("Am7", "A:min") and not majmin_equal("Am", "C:maj"))

    # Perfectly calibrated synthetic: ECE must be ~0.
    rng = np.random.default_rng(0)
    conf = np.concatenate([np.full(500, 0.9), np.full(500, 0.6)])
    correct = np.concatenate([rng.random(500) < 0.9, rng.random(500) < 0.6])
    rel = reliability(correct, conf)
    check(f"ece-small[{rel['ece']}]", rel["ece"] < 0.05)
    check("acc-sane", 0.6 < rel["accuracy"] < 0.9)

    # Overconfident synthetic: ECE must be large.
    rel2 = reliability(np.zeros(400, dtype=bool), np.full(400, 0.9))
    check(f"ece-large[{rel2['ece']}]", rel2["ece"] > 0.5)

    # Threshold sweep logic: low-conf wrong segments should flip to N
    # (N==N correct here because the ref is also N on those frames).
    ref_iv = np.array([[0.0, 10.0]])
    ref_lb = ["N"]
    est_iv = np.array([[0.0, 10.0]])
    lows = apply_threshold(["C:maj"], np.array([0.05]), 0.12)
    check("threshold-flips", lows == ["N"])
    highs = apply_threshold(["C:maj"], np.array([0.85]), 0.12)
    check("threshold-keeps", highs == ["C:maj"])
    c, _ = expand_frames(ref_iv, ref_lb, est_iv, ["N"], np.array([0.0]))
    check("all-N-correct-vs-N-ref", bool(c.all()))

    print(f"self-test: {13 + 4} checks, {failures} failures")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Chord confidence calibration (A3.3)")
    ap.add_argument("--manifest", default="manifest.json")
    ap.add_argument("--hyps-dir", default="hyps")
    ap.add_argument("--tag", default="x")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()

    manifest = json.loads((HERE / args.manifest).read_text())
    all_correct, all_conf = [], []
    per_song = []
    for song in manifest["songs"]:
        try:
            ref_iv, ref_lb = load_lab(HERE / song["ref"])
        except Exception as exc:
            print(f"SKIP {song['id']}: bad ref ({exc})")
            continue
        hyp_path = HERE / args.hyps_dir / f"{song['id']}.{args.tag}.json"
        if not hyp_path.exists():
            print(f"SKIP {song['id']}: no hyp ({hyp_path})")
            continue
        est_iv, est_lb, est_conf = load_hyp_conf(hyp_path)
        correct, conf = expand_frames(ref_iv, ref_lb, est_iv, est_lb, est_conf)
        all_correct.append(correct)
        all_conf.append(conf)
        per_song.append((song["id"], correct, conf))

    if not per_song:
        print("nothing scored — annotate refs and generate hyps first")
        return 1
    correct = np.concatenate(all_correct)
    conf = np.concatenate(all_conf)

    rel = reliability(correct, conf)
    print(f"songs={len(per_song)} frames={rel['n_frames']} "
          f"majmin-acc={rel['accuracy']} ECE={rel['ece']}")
    print(f"{'bin':>12} {'n':>7} {'conf':>7} {'acc':>7}")
    for b in rel["bins"]:
        mc = f"{b['mean_conf']:.3f}" if b["mean_conf"] is not None else "  —  "
        ac = f"{b['accuracy']:.3f}" if b["accuracy"] is not None else "  —  "
        print(f"{b['bin']:>12} {b['n']:>7} {mc:>7} {ac:>7}")

    print("\nN-threshold sweep (conf < t -> N):")
    print(f"{'t':>6} {'acc':>7} {'segments':>9}")
    best = None
    for t in np.arange(0.05, 0.325, 0.025):
        t = round(float(t), 3)
        accs, segs = [], 0
        for song in manifest["songs"]:
            try:
                ref_iv, ref_lb = load_lab(HERE / song["ref"])
            except Exception:
                continue
            hyp_path = HERE / args.hyps_dir / f"{song['id']}.{args.tag}.json"
            if not hyp_path.exists():
                continue
            est_iv, est_lb, est_conf = load_hyp_conf(hyp_path)
            thr_lb = apply_threshold(est_lb, est_conf, t)
            c, _ = expand_frames(ref_iv, ref_lb, est_iv, thr_lb, est_conf)
            accs.append(c)
            segs += len(thr_lb)
        if not accs:
            continue
        acc = float(np.concatenate(accs).mean())
        mark = "  <-- current default" if abs(t - 0.12) < 1e-9 else ""
        print(f"{t:>6.3f} {acc:>7.4f} {segs:>9}{mark}")
        if best is None or acc > best[1]:
            best = (t, acc, segs)
    if best:
        print(f"\nrecommend: N_THRESHOLD={best[0]:.3f} "
              f"(acc={best[1]:.4f}, segments={best[2]} — "
              f"apply via template engine after review, not blindly)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
