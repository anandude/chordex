#!/usr/bin/env python3
"""score_chords.py — chord recognition eval harness (A3.1).

Scores estimated chord sequences against hand-verified .lab references using
mir_eval (root / majmin / thirds / sevenths + boundary segmentation F), plus
N-coverage diagnostics. Both sides are normalized to the same Harte subset,
so the comparison is always fair.

Usage:
  # 1. score existing hypotheses (JSON from GET /api/status, or .lab):
  python score_chords.py --hyp hyps/syn_c_f_g_c.template.json --ref refs/syn_c_f_g_c.lab
  python score_chords.py --manifest manifest.json --hyps-dir hyps --tag template

  # 2. run an engine over the manifest, then score (needs backend deps):
  python score_chords.py --manifest manifest.json --run template --tag template

  # 3. dependency-free self-test (label mapping + .lab parsing only):
  python score_chords.py --self-test

Hyp JSON shape: {"chords": [{"timestamp": float, "end": float, "chord": str}],
"duration": float} — anything with a "chords" list works (extra keys ignored).
.lab shape: one "START END LABEL" triple per line, Harte labels (see README).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

try:
    from label_map import NOTES as _NOTES  # noqa: F401  (validates backend import)
except Exception:
    _NOTES = None

METRICS = ["root", "majmin", "thirds", "sevenths"]

# Our guitarSuffix -> Harte quality. Only qualities mir_eval implements stay
# exact; the rest (extensions/power chords) fold down to their triad so both
# ref and hyp are scored on identical terms (documented in README).
_HARTE_EXACT = {"": "maj", "maj": "maj", "m": "min", "min": "min",
                "7": "7", "maj7": "maj7", "m7": "min7", "min7": "min7",
                "dim": "dim", "aug": "aug", "sus2": "sus2", "sus4": "sus4"}
_HARTE_FOLD = {"5": "maj", "6": "maj", "m6": "min", "9": "7",
               "maj9": "maj7", "m9": "min7", "add9": "maj",
               "dim7": "dim", "hdim7": "dim", "m7b5": "dim", "sus": "sus4"}

_FLAT_TO_SHARP = {"Db": "C#", "Eb": "D#", "Fb": "E", "Gb": "F#",
                  "Ab": "G#", "Bb": "A#", "Cb": "B"}


def _sharp_root(raw: str) -> str | None:
    raw = raw.strip()
    if len(raw) >= 2 and raw[1] in "#b":
        root = _FLAT_TO_SHARP.get(raw[:2], raw[:2])
        return root if re.fullmatch(r"[A-G]#?", root) else None
    if raw[:1].isupper() and raw[:1] in "ABCDEFG":
        return raw[:1]
    if raw[:1].isalpha() and raw[:1].upper() in "ABCDEFG":
        return raw[:1].upper()
    return None


def to_harte(label: str) -> str:
    """Convert a Chordex guitar label (C, Am, G7, Dm7, Dsus4, G/B, N, …)
    to Harte syntax mir_eval understands (C:maj, A:min, G:7, D:sus4, G:maj/B, N).
    """
    if label is None:
        return "N"
    s = str(label).strip()
    if not s or s.upper() in {"N", "NC", "N.C.", "NONE", "X", "SILENCE"}:
        return "N"
    if ":" in s:
        root_part, quality_part = s.split(":", 1)
    else:
        m = re.match(r"^([A-Ga-g][#b]?)(.*)$", s)
        if not m:
            return "N"
        root_part, quality_part = m.group(1), m.group(2)
    root = _sharp_root(root_part)
    if root is None:
        return "N"
    quality_part = quality_part.strip().replace(" ", "")
    bass = ""
    if "/" in quality_part:
        quality_part, bass_raw = quality_part.split("/", 1)
        bass_note = _sharp_root(bass_raw)
        bass = f"/{bass_note}" if bass_note else ""
    q = quality_part.replace("major", "maj").replace("minor", "min")
    if q.lower() in _HARTE_EXACT:
        q = _HARTE_EXACT[q.lower()]
    elif q in _HARTE_FOLD:
        q = _HARTE_FOLD[q]
    elif q.lower() in _HARTE_FOLD:
        q = _HARTE_FOLD[q.lower()]
    else:
        # Unknown extension: keep the triad family by leading-m heuristic so
        # scoring never crashes on unseen labels (lenient by design).
        q = "min" if q.startswith(("m", "min")) and not q.startswith("maj") else "maj"
    return f"{root}:{q}{bass}"


def load_lab(path: Path) -> tuple[np.ndarray, list[str]]:
    """Parse a .lab file -> (Nx2 float intervals, Harte labels)."""
    intervals: list[list[float]] = []
    labels: list[str] = []
    for lineno, line in enumerate(Path(path).read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 3:
            raise ValueError(f"{path}:{lineno}: expected 'START END LABEL'")
        start, end = float(parts[0]), float(parts[1])
        if not end > start:
            raise ValueError(f"{path}:{lineno}: END must exceed START")
        intervals.append([start, end])
        labels.append(to_harte(" ".join(parts[2:])))
    if not intervals:
        raise ValueError(f"{path}: no intervals found")
    return np.asarray(intervals, dtype=float), labels


def load_hyp(path: Path) -> tuple[np.ndarray, list[str]]:
    """Load an estimate from Chordex result JSON or .lab -> (intervals, labels)."""
    path = Path(path)
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text())
        chords = data.get("chords", [])
        duration = data.get("duration")
        intervals, labels = [], []
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
        if not intervals:
            raise ValueError(f"{path}: no chord events found")
        return np.asarray(intervals, dtype=float), labels
    return load_lab(path)


def _as_float(value) -> float:
    if isinstance(value, (tuple, list)):
        value = value[0]
    return float(value)


def score_pair(ref_iv: np.ndarray, ref_lb: list[str],
               est_iv: np.ndarray, est_lb: list[str]) -> dict:
    """mir_eval chord scores for one song. Raises ImportError if mir_eval is missing."""
    try:
        import mir_eval.chord as _chord
    except ImportError as exc:
        raise ImportError(
            "mir_eval is required for scoring (pip install mir_eval). "
            "Label mapping can still be tested with --self-test."
        ) from exc

    # Compare over the reference duration; trim stray estimate tails.
    ref_end = float(ref_iv[-1, 1])
    est_iv = np.asarray(est_iv, dtype=float)
    est_iv[:, 1] = np.minimum(est_iv[:, 1], ref_end)
    keep = est_iv[:, 1] > est_iv[:, 0]
    est_iv, est_lb = est_iv[keep], [est_lb[i] for i in np.nonzero(keep)[0]]

    out: dict = {}
    for name in METRICS:
        fn = getattr(_chord, name)
        try:
            out[name] = round(_as_float(fn(ref_iv, ref_lb, est_iv, est_lb)), 4)
        except Exception as exc:
            out[name] = f"ERROR: {exc}"
    try:
        seg = _chord.seg(ref_iv, est_iv)
        p, r, f = (float(v) for v in seg[:3])
        out["seg_p"], out["seg_r"], out["seg_f"] = round(p, 4), round(r, 4), round(f, 4)
    except Exception as exc:
        out["seg_p"] = out["seg_r"] = out["seg_f"] = f"ERROR: {exc}"
    # Diagnostics: how much audio the engine left as no-chord, and how jumpy.
    n_dur = sum(e - s for (s, e), l in zip(est_iv, est_lb) if l == "N")
    out["n_frac"] = round(float(n_dur) / ref_end, 4) if ref_end > 0 else 0.0
    out["n_segments"] = len(est_lb)
    return out


def run_engine(engine: str, audio: Path, out_path: Path) -> Path:
    """Run a Chordex engine over one file, save the result JSON. Needs backend deps."""
    sys.path.insert(0, str(BACKEND))
    from chord_engine import get_engine

    result = get_engine(engine).analyze(str(audio))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=1))
    return out_path


def self_test() -> int:
    """Dependency-free checks: Harte mapping + .lab parsing + hyp loading."""
    cases = {
        "C": "C:maj", "Am": "A:min", "G7": "G:7", "Dm7": "D:min7",
        "Cmaj7": "C:maj7", "F#dim": "F#:dim", "Bbaug": "A#:aug",
        "Dsus4": "D:sus4", "Gsus2": "G:sus2", "A5": "A:maj",
        "C9": "C:7", "Fmaj9": "F:maj7", "Bm7b5": "B:dim",
        "G/B": "G:maj/B", "N": "N", "": "N", "n.c.": "N",
        "C:maj": "C:maj", "A:min7": "A:min7", "Bb:maj7": "A#:maj7",
    }
    failures = 0
    for raw, want in cases.items():
        got = to_harte(raw)
        if got != want:
            print(f"FAIL to_harte({raw!r}) = {got!r}, want {want!r}")
            failures += 1
    for name in ("syn_c_major", "syn_c_f_g_c"):
        iv, lb = load_lab(HERE / "refs" / f"{name}.lab")
        assert (iv[:, 1] > iv[:, 0]).all(), name
        assert all(isinstance(l, str) for l in lb), name
    print(f"self-test: {len(cases)} mapping cases + 2 ref files, {failures} failures")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Chord eval harness (A3.1)")
    ap.add_argument("--ref", help="reference .lab for single-song mode")
    ap.add_argument("--hyp", help="hypothesis (.lab or Chordex result .json)")
    ap.add_argument("--manifest", default="manifest.json", help="manifest for batch mode")
    ap.add_argument("--hyps-dir", default="hyps", help="dir holding <song_id>.<tag>.json")
    ap.add_argument("--tag", default="x", help="hyp filename tag for batch mode")
    ap.add_argument("--run", metavar="ENGINE",
                    help="run this Chordex engine over the manifest first")
    ap.add_argument("--self-test", action="store_true", help="dependency-free checks")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if args.ref and args.hyp:
        ref_iv, ref_lb = load_lab(Path(args.ref))
        est_iv, est_lb = load_hyp(Path(args.hyp))
        try:
            print(json.dumps(score_pair(ref_iv, ref_lb, est_iv, est_lb), indent=1))
        except ImportError as exc:
            print(f"ABORT: {exc}")
            return 2
        return 0

    manifest_path = HERE / args.manifest
    manifest = json.loads(manifest_path.read_text())
    hyps_dir = HERE / args.hyps_dir
    rows: list[dict] = []
    for song in manifest["songs"]:
        # A3.2: one bad song (missing ref, unannotated stub, corrupt hyp)
        # must never abort the whole batch — SKIP loudly instead.
        try:
            ref_iv, ref_lb = load_lab(HERE / song["ref"])
        except Exception as exc:
            print(f"SKIP {song['id']}: bad ref ({exc})")
            continue
        hyp_path = hyps_dir / f"{song['id']}.{args.tag}.json"
        if args.run:
            audio = (HERE / song["audio"]).resolve()
            if not audio.exists():
                print(f"SKIP {song['id']}: audio missing ({audio})")
                continue
            try:
                run_engine(args.run, audio, hyp_path)
            except Exception as exc:
                print(f"SKIP {song['id']}: engine failed ({exc})")
                continue
        if not hyp_path.exists():
            print(f"SKIP {song['id']}: no hyp ({hyp_path})")
            continue
        try:
            est_iv, est_lb = load_hyp(hyp_path)
            row = {"song": song["id"], **score_pair(ref_iv, ref_lb, est_iv, est_lb)}
        except ImportError as exc:
            print(f"ABORT: {exc}")
            return 2
        except Exception as exc:
            print(f"SKIP {song['id']}: bad hyp ({exc})")
            continue
        rows.append(row)
        print(f"{song['id']}: " + " ".join(
            f"{m}={row[m]}" for m in METRICS + ["seg_f"]))
    if rows:
        print(f"\nmeans over {len(rows)} songs: " + " ".join(
            f"{m}={round(float(np.mean([r[m] for r in rows])), 4)}"
            for m in METRICS + ["seg_f"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
