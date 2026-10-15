"""
pipeline/alignment.py
---------------------
Phase 4 — CTC forced alignment for word (and syllable) timing.

Whisper's word stamps come from cross-attention DTW and drift by 0.3–1 s on
sung vocals; LRCLIB gives line stamps only. We re-align whichever text we have
against the vocal stem with Meta's MMS forced-alignment acoustic model
(``torchaudio.pipelines.MMS_FA``, 1000+ languages via romanisation) and our
own CTC Viterbi (``ctc_viterbi`` — small, unit-tested, no dependency on
torchaudio's deprecated ``forced_align``).

History: this module used to import PyPI ``ctc-forced-aligner==1.0.2``, which
turned out to be an unrelated ONNX/English-only package — the import always
failed and every job silently fell back to even-split timing.

How it works:
  1. Emissions (50 frames/s log-probs over a 27-letter romanised alphabet) are
     computed ONCE for the whole stem, in 30 s windows with context.
  2. Each native-script word is romanised on its own with ``uroman`` (keeps
     a 1:1 native↔roman word map — no more truncation on count mismatches).
  3. Text is aligned PER LINE inside a padded window around the line's rough
     time (Whisper words or LRCLIB line stamps), so words cannot drift into
     instrumental gaps. Untimed text gets one whole-song pass instead.
  4. Each word gets ``confidence`` (mean frame posterior) and ``splits``:
     syllable onsets inside the word ``[{"i": native_char_idx, "t": sec}]`` —
     what lets a chord land mid-word ("beau-[G]tiful").

Timebase: seconds from 0 of the stem, which shares the upload's origin.

⚠️ LICENSING: MMS_FA weights are CC-BY-NC-4.0 (non-commercial). The project is
personal-use only (THIRD_PARTY_NOTICES.md). The backend is swappable via ``ALIGN_FN``.
"""

from __future__ import annotations

import logging
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable

import numpy as np

from pipeline.config import LyricsConfig

logger = logging.getLogger(__name__)

SR = 16000
FPS = 50.0  # MMS_FA frame rate (stride 320 samples)
_ISO3 = {"hi": "hin", "ml": "mal", "en": "eng", "ta": "tam"}
_MAX_WORD_S = 4.0
_LINE_PAD_S = 0.6       # window padding around a Whisper-timed line
_LRC_PAD_S = 1.0        # LRCLIB stamps are coarser
_LINE_GAP_S = 1.0       # Whisper words further apart start a new window
_MAX_WINDOW_S = 15.0
_MIN_LINE_CONF = 0.15   # below this the alignment is not trusted
_VOWELS = set("aeiou")
_VIRAMAS = {"्", "്", "்", "‍", "‌"}

_model_cache: dict[str, Any] = {}
_uroman: Any = None

# Swappable aligner backend (commercial-safe alternative drops in here).
ALIGN_FN: Callable[..., list[dict[str, Any]] | None] | None = None


# ── CTC Viterbi (pure numpy) ──────────────────────────────────────────────

def ctc_viterbi(log_probs: np.ndarray, tokens: list[int], blank: int = 0
                ) -> np.ndarray | None:
    """Best CTC path for ``tokens`` through ``log_probs`` (T, C).

    Returns, per frame, the index of the token it emits (-1 = blank), or None
    when the sequence cannot fit in T frames.
    """
    T = log_probs.shape[0]
    L = len(tokens)
    if L == 0:
        return np.full(T, -1, dtype=np.int32)
    ext = np.full(2 * L + 1, blank, dtype=np.int64)
    ext[1::2] = tokens
    S = len(ext)
    repeats = sum(1 for a, b in zip(tokens, tokens[1:]) if a == b)
    if T < L + repeats:
        return None
    allow2 = np.zeros(S, dtype=bool)
    allow2[3::2] = ext[3::2] != ext[1:-2:2]  # skip blank between distinct tokens
    neg = -np.inf
    alpha = np.full(S, neg)
    alpha[0] = log_probs[0, blank]
    alpha[1] = log_probs[0, ext[1]]
    bp = np.zeros((T, S), dtype=np.int8)
    for t in range(1, T):
        a1 = np.concatenate(([neg], alpha[:-1]))
        a2 = np.concatenate(([neg, neg], alpha[:-2]))
        a2[~allow2] = neg
        stack = np.stack([alpha, a1, a2])
        choice = np.argmax(stack, axis=0)
        alpha = stack[choice, np.arange(S)] + log_probs[t, ext]
        bp[t] = choice
    s = S - 1 if alpha[S - 1] >= alpha[S - 2] else S - 2
    if not np.isfinite(alpha[s]):
        return None
    path = np.empty(T, dtype=np.int32)
    for t in range(T - 1, -1, -1):
        path[t] = (s - 1) // 2 if s % 2 == 1 else -1
        s -= int(bp[t, s])
    return path


# ── romanisation + split points ───────────────────────────────────────────

def _romanise(word: str, lang3: str, vocab: dict[str, int]) -> str:
    global _uroman
    text = word
    if not word.isascii():
        try:
            if _uroman is None:
                import uroman

                _uroman = uroman.Uroman()
            text = _uroman.romanize_string(word, lcode=lang3)
        except Exception as exc:
            logger.debug("uroman failed on %r (%s)", word, exc)
    text = unicodedata.normalize("NFKD", str(text).lower())
    return "".join(ch for ch in text if ch in vocab and ch != "-")


def _grapheme_safe(native: str, idx: int) -> int:
    """Move a split index forward until it starts a new grapheme cluster
    (never between a consonant and its vowel sign / after a virama)."""
    while 0 < idx < len(native) and (
        unicodedata.category(native[idx]).startswith("M")
        or native[idx - 1] in _VIRAMAS
        or native[idx] in _VIRAMAS
    ):
        idx += 1
    return idx


def split_points(native: str, roman: str, char_times: list[float]) -> list[dict[str, Any]]:
    """Syllable onsets inside a word → [{"i": native_idx, "t": seconds}].

    Onset = a consonant followed by a vowel, or a vowel after a vowel-less
    stretch, in the romanisation. The native index is mapped proportionally
    and snapped to a grapheme boundary. Word start (i=0) is excluded.
    """
    out: list[dict[str, Any]] = []
    if len(roman) < 3 or len(char_times) != len(roman) or len(native) < 2:
        return out
    seen: set[int] = set()
    for j in range(1, len(roman) - 1):
        c, nxt, prev = roman[j], roman[j + 1], roman[j - 1]
        onset = (c not in _VOWELS and nxt in _VOWELS and prev in _VOWELS) or (
            c not in _VOWELS and nxt in _VOWELS and prev not in _VOWELS and j >= 2
            and roman[j - 2] in _VOWELS)
        if not onset:
            continue
        i = _grapheme_safe(native, round(j / len(roman) * len(native)))
        if 0 < i < len(native) and i not in seen:
            seen.add(i)
            out.append({"i": i, "t": round(float(char_times[j]), 3)})
    return out


# ── model + emissions ─────────────────────────────────────────────────────

def _get_model(cfg: LyricsConfig):
    if "mms_fa" in _model_cache:
        return _model_cache["mms_fa"]
    import torch
    import torchaudio

    device = cfg.torch_device()
    bundle = torchaudio.pipelines.MMS_FA
    logger.info("loading MMS_FA aligner (runs on %s)", device)
    # fp32 even on CUDA: on a GTX 1650 (Turing, no tensor cores) the fp16
    # wav2vec2 forward measured 4.4x SLOWER (2.65 s vs 0.60 s per 19 s chunk).
    # Cached on CPU; compute_emissions moves it to the GPU only while it runs
    # (1.2 GB of weights must not sit next to Whisper on a 4 GB card).
    model = bundle.get_model(with_star=False).eval()
    vocab = bundle.get_dict(star=None)
    _model_cache["mms_fa"] = (model, vocab, device, torch)
    return _model_cache["mms_fa"]


def compute_emissions(y: np.ndarray, cfg: LyricsConfig, window_s: float = 15.0,
                      context_s: float = 2.0) -> tuple[np.ndarray, dict[str, int]]:
    """(T, C) float32 log-probs at 50 fps for the whole stem.

    15 s windows keep peak activation memory well under 1 GB, so the model
    fits next to Whisper on a 4 GB card that also drives the desktop."""
    model, vocab, device, torch = _get_model(cfg)
    win, ctx = int(window_s * SR), int(context_s * SR)
    dtype = next(model.parameters()).dtype
    chunks: list[np.ndarray] = []
    try:
        model.to(device)
    except RuntimeError as exc:  # no VRAM left → align on CPU this time
        logger.warning("aligner on %s failed (%s) — cpu", device, exc)
        device = "cpu"
        model.to(device)
    try:
        _emit(model, y, win, ctx, device, dtype, torch, chunks)
    finally:
        if device != "cpu":
            model.to("cpu")
            torch.cuda.empty_cache()
    return np.concatenate(chunks) if chunks else np.zeros((0, len(vocab))), vocab


def _emit(model, y, win, ctx, device, dtype, torch, chunks) -> None:
    with torch.inference_mode():
        for start in range(0, max(1, len(y)), win):
            a, b = max(0, start - ctx), min(len(y), start + win + ctx)
            x = torch.from_numpy(y[a:b]).to(device=device, dtype=dtype).unsqueeze(0)
            em, _ = model(x)
            em = torch.log_softmax(em.float(), dim=-1)[0].cpu().numpy()
            f = em.shape[0] / max(1, (b - a))  # frames per sample
            lo = int(round((start - a) * f))
            hi = lo + int(round((min(start + win, len(y)) - start) * f))
            chunks.append(em[lo:hi])


# ── line windows ──────────────────────────────────────────────────────────

def _lines_lack_timing(lines: list[dict[str, Any]]) -> bool:
    """True when lines carry no usable timing (all zeros) — the shape that
    used to collapse the chord sheet into detached rows and freeze karaoke
    at 0:00. Such lines must be spread across the duration before use."""
    if not lines:
        return True
    return all(
        float(l.get("timestamp", 0) or 0) == 0.0 and float(l.get("end", 0) or 0) == 0.0
        for l in lines
    )


def _groups_from_words(words: list[dict[str, Any]]) -> list[list[int]]:
    """Whisper-timed words → index groups (one alignment window each)."""
    groups: list[list[int]] = []
    for i, w in enumerate(words):
        if groups:
            first, last = words[groups[-1][0]], words[groups[-1][-1]]
            gap = float(w["timestamp"]) - float(last.get("end", last["timestamp"]))
            span = float(w.get("end", w["timestamp"])) - float(first["timestamp"])
            if gap <= _LINE_GAP_S and span <= _MAX_WINDOW_S:
                groups[-1].append(i)
                continue
        groups.append([i])
    return groups


def _align_window(em: np.ndarray, t0: float, romans: list[str], vocab: dict[str, int]
                  ) -> list[dict[str, Any]] | None:
    """Align romanised words inside emission frames starting at time t0."""
    tokens: list[int] = []
    owner: list[tuple[int, int]] = []  # token → (word idx, char idx)
    for wi, r in enumerate(romans):
        for ci, ch in enumerate(r):
            tokens.append(vocab[ch])
            owner.append((wi, ci))
    if not tokens:
        return None
    path = ctc_viterbi(em, tokens, blank=vocab.get("-", 0))
    if path is None:
        return None
    first = np.full(len(tokens), -1)
    last = np.full(len(tokens), -1)
    for f, k in enumerate(path):
        if k >= 0:
            if first[k] < 0:
                first[k] = f
            last[k] = f
    probs = np.exp(em[np.arange(len(path)), [tokens[k] if k >= 0 else 0 for k in path]])
    out: list[dict[str, Any] | None] = [None] * len(romans)
    for wi in range(len(romans)):
        ks = [k for k, (w, _) in enumerate(owner) if w == wi]
        if not ks:
            continue
        frames = [f for f, k in enumerate(path) if k in ks]
        out[wi] = {
            "timestamp": t0 + first[ks[0]] / FPS,
            "end": t0 + (last[ks[-1]] + 1) / FPS,
            "confidence": float(np.mean(probs[frames])) if frames else 0.0,
            "char_times": [t0 + first[k] / FPS for k in ks],
        }
    return out  # type: ignore[return-value]


def align(
    vocal_stem_path: str | Path,
    text: str | None = None,
    language: str | None = None,
    *,
    lines: list[dict[str, Any]] | None = None,
    words: list[dict[str, Any]] | None = None,
    duration: float | None = None,
    cfg: LyricsConfig | None = None,
    audio: np.ndarray | None = None,
) -> dict[str, Any]:
    """Return ``{words: [{word, timestamp, end, confidence, splits}], lines,
    backend, error}``. ``lines`` carry ``w0``/``w1`` (word index range).
    Never raises — falls back to the input timing / even split."""
    from pipeline.lyrics_lookup import spread_lines, words_even_split

    cfg = cfg or LyricsConfig.from_env()
    lang3 = _ISO3.get((language or "").lower(), "eng")

    # ── normalise input into native words + line groups + rough windows ──
    src_lines = [dict(l) for l in (lines or [])]
    if words:
        native = [dict(w) for w in words if w.get("word")]
        groups = _groups_from_words(native)
        windows = [(float(native[g[0]]["timestamp"]) - _LINE_PAD_S,
                    float(native[g[-1]].get("end", native[g[-1]]["timestamp"])) + _LINE_PAD_S)
                   for g in groups]
        timed_lines = False
    else:
        if not src_lines and text:
            src_lines = [{"timestamp": 0.0, "end": 0.0, "text": t}
                         for t in text.splitlines() if t.strip()]
        untimed = _lines_lack_timing(src_lines)
        if untimed:
            src_lines = spread_lines([l.get("text", "") for l in src_lines] or [text or ""],
                                     duration)
        # rough per-word times: even split inside each line (same tokenisation)
        native = words_even_split(src_lines)
        groups = _line_groups(src_lines)
        windows = [(float(l["timestamp"]) - _LRC_PAD_S,
                    float(l.get("end", l["timestamp"])) + _LRC_PAD_S)
                   for l in src_lines if l.get("text", "").split()]
        timed_lines = not untimed
        if untimed:  # one whole-song pass instead of guessed windows
            windows = [(0.0, float("inf"))]
            groups = [list(range(len(native)))]
    if not native:
        return {"words": [], "lines": src_lines, "backend": "none", "error": "empty text"}

    def _fallback(note: str, backend: str) -> dict[str, Any]:
        if words:
            fw = [{**w, "confidence": None} for w in native]
            return {"words": fw, "lines": _lines_for(fw, groups), "backend": backend,
                    "error": note}
        fl = src_lines
        ew = words_even_split(fl)
        return {"words": ew, "lines": fl, "backend": backend, "error": note}

    if not cfg.alignment_enabled:
        return _fallback("disabled", "even-split" if not words else "whisper")
    if ALIGN_FN is not None:
        try:
            custom = ALIGN_FN(vocal_stem_path, [w["word"] for w in native], lang3)
            if custom:
                return {"words": custom, "lines": src_lines, "backend": "custom", "error": None}
        except Exception as exc:
            logger.warning("custom aligner failed (%s)", exc)

    t_start = time.time()
    try:
        from pipeline.asr import load_stem

        y = audio if audio is not None else load_stem(vocal_stem_path)
        em, vocab = compute_emissions(y, cfg)
        total_s = em.shape[0] / FPS
        romans = [_romanise(w["word"], lang3, vocab) for w in native]

        out_words: list[dict[str, Any]] = []
        low_conf = failed_lines = 0
        prev_end = 0.0
        for g, (ws, we) in zip(groups, windows):
            ws = max(prev_end, ws, 0.0)
            we = min(total_s, we)
            res = None
            for widen in (0.0, 1.5):  # one retry with a wider window
                a, b = max(prev_end, ws - widen), min(total_s, we + widen)
                if b - a > 0.2:
                    res = _align_window(em[int(a * FPS):int(b * FPS)], a,
                                        [romans[i] for i in g], vocab)
                if res is not None:
                    break
            confs = [r["confidence"] for r in (res or []) if r]
            trusted = res is not None and confs and float(np.mean(confs)) >= _MIN_LINE_CONF
            if not trusted:
                failed_lines += 1
            for k, i in enumerate(g):
                w = native[i]
                r = res[k] if trusted and res else None
                if r is None:
                    # untrusted / unromanisable: keep rough timing, clamp monotonic
                    s = max(float(w["timestamp"]), prev_end)
                    e = max(float(w.get("end", s + 0.3)), s + 0.05)
                    out_words.append({"word": w["word"], "timestamp": round(s, 3),
                                      "end": round(e, 3), "confidence": None, "splits": []})
                    prev_end = e
                    continue
                s = max(r["timestamp"], prev_end)
                e = min(max(r["end"], s + 0.05), s + _MAX_WORD_S)
                if r["confidence"] < 0.3:
                    low_conf += 1
                out_words.append({
                    "word": w["word"], "timestamp": round(s, 3), "end": round(e, 3),
                    "confidence": round(r["confidence"], 3),
                    "splits": split_points(w["word"], romans[i], r["char_times"]),
                })
                prev_end = e

        if not words and not timed_lines:
            # untimed text: words without rough times sit between aligned ones
            _interpolate_missing(out_words)
        out_lines = _lines_for(out_words, groups if words or timed_lines
                               else _line_groups(src_lines))
        logger.info("align ok lang=%s words=%d low_conf=%d untrusted_lines=%d/%d in %.1fs",
                    lang3, len(out_words), low_conf, failed_lines, len(groups),
                    time.time() - t_start)
        note = None
        if low_conf or failed_lines:
            note = f"{low_conf} low-confidence words, {failed_lines} unaligned lines"
        return {"words": out_words, "lines": out_lines, "backend": "mms-fa", "error": note}
    except ImportError as exc:
        logger.info("aligner deps missing (%s) — fallback timing", exc)
        return _fallback(f"aligner unavailable: {exc}", "even-split" if not words else "whisper")
    except Exception as exc:
        logger.warning("alignment failed (%s) — fallback timing", exc)
        return _fallback(str(exc)[:300], "even-split" if not words else "whisper")


def _line_groups(src_lines: list[dict[str, Any]]) -> list[list[int]]:
    groups, n = [], 0
    for l in src_lines:
        k = len(l.get("text", "").split())
        if k:
            groups.append(list(range(n, n + k)))
            n += k
    return groups


def _lines_for(words: list[dict[str, Any]], groups: list[list[int]]) -> list[dict[str, Any]]:
    """Lines (with word index range w0..w1 inclusive) timed from their words."""
    out = []
    for g in groups:
        g = [i for i in g if i < len(words)]
        if not g:
            continue
        out.append({
            "timestamp": words[g[0]]["timestamp"],
            "end": words[g[-1]].get("end", words[g[-1]]["timestamp"]),
            "text": " ".join(words[i]["word"] for i in g),
            "w0": g[0], "w1": g[-1],
        })
    return out


def _interpolate_missing(words: list[dict[str, Any]]) -> None:
    """Words left without a trusted time get evenly spaced between the nearest
    trusted neighbours (in place)."""
    idx = [i for i, w in enumerate(words) if w.get("confidence") is not None]
    if not idx:
        return
    for a, b in zip([-1] + idx, idx + [len(words)]):
        gap = list(range(a + 1, b))
        if not gap:
            continue
        lo = words[a]["end"] if a >= 0 else max(0.0, words[b]["timestamp"] - 0.4 * len(gap))
        hi = words[b]["timestamp"] if b < len(words) else lo + 0.4 * len(gap)
        step = max(0.05, (hi - lo) / len(gap))
        for k, i in enumerate(gap):
            words[i]["timestamp"] = round(lo + k * step, 3)
            words[i]["end"] = round(lo + (k + 1) * step, 3)

