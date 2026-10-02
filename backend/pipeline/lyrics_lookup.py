"""
pipeline/lyrics_lookup.py
-------------------------
Phase 2 — LRCLIB as the primary lyrics source. The best transcription is the
one you don't have to do: exact lookup first, fuzzy search second, ASR
fallback on miss (handled by the caller).

Verified against the live API (``GET /api/search`` smoke-tested): responses
carry ``trackName/artistName/albumName/duration/instrumental/plainLyrics/
syncedLyrics``. ``GET /api/get`` + ``GET /api/get/{id}`` are used defensively
(the API is beta) — any shape mismatch degrades to a miss, never an exception.

Result carries ``source``: ``lrclib_synced | lrclib_plain | asr`` so the UI can
distinguish verified lyrics from machine transcription.
"""

from __future__ import annotations

import difflib
import logging
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from pipeline.cache import stage_cache_path
from pipeline.config import LyricsConfig

logger = logging.getLogger(__name__)

API_BASE = "https://lrclib.net"
_LRC_TS = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
_DURATION_TOLERANCE_S = 3.0
_TITLE_MIN_RATIO = 0.6
_ARTIST_MIN_RATIO = 0.5


# ── metadata ──────────────────────────────────────────────────────────────

def _tags_from_file(audio_path: Path) -> dict[str, str]:
    """ID3/metadata tags via mutagen (optional dep — missing file types ok)."""
    meta: dict[str, str] = {}
    try:
        from mutagen import File as MutagenFile

        audio = MutagenFile(str(audio_path), easy=True)
        if not audio:
            return meta
        for key in ("title", "artist", "album"):
            vals = audio.get(key)
            if vals:
                meta[key] = str(vals[0]).strip()
    except ImportError:
        logger.debug("mutagen not installed — filename heuristics only")
    except Exception as exc:
        logger.debug("tag read failed (%s)", exc)
    return meta


def _tags_from_filename(audio_path: Path) -> dict[str, str]:
    """Heuristics: 'Artist - Title.ext', 'Title (Film).ext', '01 Title.ext'."""
    stem = audio_path.stem.strip()
    meta: dict[str, str] = {}
    m = re.match(r"^\s*(.+?)\s*[-–—]\s*(.+?)\s*$", stem)
    if m:
        meta["artist"] = m.group(1).strip()
        meta["title"] = m.group(2).strip()
    else:
        meta["title"] = re.sub(r"^\d{1,3}[\s._-]+", "", stem).strip()
    # Common film tag: "Song (Film Name)" → album = Film Name
    m2 = re.match(r"^(.*?)\s*\(([^)]+)\)\s*$", meta.get("title", ""))
    if m2 and m2.group(1).strip():
        meta["title"] = m2.group(1).strip()
        meta.setdefault("album", m2.group(2).strip())
    return {k: v for k, v in meta.items() if v}


def get_metadata(
    audio_path: str | Path,
    title_hint: str | None = None,
    artist_hint: str | None = None,
    album_hint: str | None = None,
) -> dict[str, str]:
    """Precedence: (a) explicit UI fields, (b) file tags, (c) filename."""
    audio_path = Path(audio_path)
    meta = _tags_from_filename(audio_path)
    meta.update({k: v for k, v in _tags_from_file(audio_path).items() if v})
    for key, hint in (("title", title_hint), ("artist", artist_hint), ("album", album_hint)):
        if hint and hint.strip():
            meta[key] = hint.strip()
    return meta


def audio_duration_s(audio_path: str | Path) -> float | None:
    try:
        import librosa

        return float(librosa.get_duration(path=str(audio_path)))
    except Exception:
        return None


# ── HTTP ──────────────────────────────────────────────────────────────────

def _get_json(url: str, params: dict[str, Any], cfg: LyricsConfig) -> Any | None:
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(
        f"{url}?{qs}" if qs else url,
        headers={"User-Agent": cfg.user_agent, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg.lrclib_timeout_s) as resp:
            import json

            if resp.status != 200:
                return None
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:
        logger.debug("lrclib request failed (%s)", exc)
        return None


# ── matching ──────────────────────────────────────────────────────────────

def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _accept(
    candidate: dict[str, Any], meta: dict[str, str], duration: float | None
) -> bool:
    if not isinstance(candidate, dict):
        return False
    if candidate.get("instrumental"):
        return False
    if not (candidate.get("plainLyrics") or candidate.get("syncedLyrics")):
        return False
    if duration is not None and candidate.get("duration") is not None:
        try:
            if abs(float(candidate["duration"]) - duration) > _DURATION_TOLERANCE_S:
                return False
        except (TypeError, ValueError):
            return False
    title = meta.get("title", "")
    if title and candidate.get("trackName"):
        if _ratio(title, str(candidate["trackName"])) < _TITLE_MIN_RATIO:
            return False
    artist = meta.get("artist", "")
    if artist and candidate.get("artistName"):
        if _ratio(artist, str(candidate["artistName"])) < _ARTIST_MIN_RATIO:
            return False
    return True


def _pick_best(
    candidates: Any, meta: dict[str, str], duration: float | None
) -> dict[str, Any] | None:
    if isinstance(candidates, dict):
        candidates = [candidates]
    if not isinstance(candidates, list):
        return None
    scored: list[tuple[float, dict[str, Any]]] = []
    for c in candidates:
        if not _accept(c, meta, duration):
            continue
        score = 0.0
        if meta.get("title") and c.get("trackName"):
            score += _ratio(meta["title"], str(c["trackName"]))
        if meta.get("artist") and c.get("artistName"):
            score += 0.5 * _ratio(meta["artist"], str(c["artistName"]))
        scored.append((score, c))
    if not scored:
        return None
    scored.sort(key=lambda t: t[0], reverse=True)
    return scored[0][1]


# ── LRC parsing ───────────────────────────────────────────────────────────

def parse_synced_lyrics(synced: str) -> list[dict[str, Any]]:
    """``[mm:ss.xx] line`` → [{timestamp, end, text}]. End = next line start."""
    lines: list[dict[str, Any]] = []
    for raw in (synced or "").splitlines():
        stamps = _LRC_TS.findall(raw)
        text = _LRC_TS.sub("", raw).strip()
        if not stamps or not text:
            continue
        mm, ss, frac = stamps[0]
        ts = int(mm) * 60 + int(ss)
        if frac:
            scale = 10 ** len(frac)
            ts += int(frac) / scale
        lines.append({"timestamp": round(ts, 3), "text": text})
    lines.sort(key=lambda l: l["timestamp"])
    for i, line in enumerate(lines):
        line["end"] = (
            round(lines[i + 1]["timestamp"], 3) if i + 1 < len(lines) else round(line["timestamp"] + 4.0, 3)
        )
    return lines


def words_even_split(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fallback word timings: distribute words evenly across their line span
    (replaced by Phase 4 forced alignment when enabled). Lines with no timing
    info (all zeros) must be spread first via spread_lines — never split in
    place, which crams every word into [0, 0.3]."""
    words: list[dict[str, Any]] = []
    for line in lines:
        tokens = line["text"].split()
        if not tokens:
            continue
        span = max(0.3, line["end"] - line["timestamp"])
        per = span / len(tokens)
        for i, tok in enumerate(tokens):
            s = line["timestamp"] + i * per
            words.append({"timestamp": round(s, 3), "end": round(s + per, 3), "word": tok})
    return words


def spread_lines(texts: list[str], duration: float | None) -> list[dict[str, Any]]:
    """Distribute untimed lines evenly across the song duration.

    Used for LRCLIB plain lyrics and every even-split fallback: without this,
    downstream code sees N lines stacked at [0, 0] (sheet degenerates into
    detached chord rows, karaoke highlight never moves). Unknown duration →
    4 s per line starting at 0 (audible, debuggable, never overlapping).
    """
    lines: list[dict[str, Any]] = []
    if duration and duration > 0:
        per = duration / len(texts)
        for i, t in enumerate(texts):
            lines.append({
                "timestamp": round(i * per, 3),
                "end": round((i + 1) * per, 3),
                "text": t,
            })
    else:
        for i, t in enumerate(texts):
            lines.append({
                "timestamp": round(i * 4.0, 3),
                "end": round(i * 4.0 + 4.0, 3),
                "text": t,
            })
    return lines


def _ensure_plain_timing(result: dict[str, Any] | None,
                           duration: float | None) -> dict[str, Any] | None:
    """Heal cached/fresh plain-lyric rows that pre-date line timing.

    Pre-fix caches store every plain line at [0, duration], which collapses
    the chord sheet. Re-spread them; synced rows and timed rows pass through
    untouched. Never raises (returns input on any doubt).
    """
    try:
        if not isinstance(result, dict) or result.get("source") != "lrclib_plain":
            return result
        lines = result.get("lines") or []
        if not lines:
            return result
        bad = all(
            float(l.get("timestamp", 0) or 0) == 0.0 for l in lines
        ) and len(lines) > 1
        if bad:
            result["lines"] = spread_lines(
                [l.get("text", "") for l in lines], duration
            )
            result["lyrics"] = words_even_split(result["lines"])
    except Exception:
        pass
    return result


def _plain_lines_even(plain: str, duration: float | None) -> list[dict[str, Any]]:
    """LRCLIB plain (unsynced) lyrics -> timed lines spread across duration."""
    texts = [t.strip() for t in (plain or "").splitlines() if t.strip()]
    if not texts:
        return []
    return spread_lines(texts, duration)


# ── entry point ───────────────────────────────────────────────────────────

def lookup_lyrics(
    audio_path: str | Path,
    *,
    title: str | None = None,
    artist: str | None = None,
    album: str | None = None,
    duration: float | None = None,
    cfg: LyricsConfig | None = None,
) -> dict[str, Any] | None:
    """Return ``{source, lines, lyrics, language, track}`` or None on miss.

    ``lines`` always carry timestamps; ``lyrics`` (words) come from even-split
    unless Phase 4 re-aligns them downstream.
    """
    cfg = cfg or LyricsConfig.from_env()
    if not cfg.lrclib_enabled:
        return None
    audio_path = Path(audio_path)
    meta = get_metadata(audio_path, title, artist, album)
    if not meta.get("title"):
        logger.info("lrclib: no title metadata — skipping lookup")
        return None
    if duration is None:
        duration = audio_duration_s(audio_path)

    cache = stage_cache_path(
        cfg.cache_dir, "lrclib", audio_path,
        meta.get("title", ""), meta.get("artist", ""), str(duration or 0),
    )
    if cache.exists():
        from pipeline.cache import read_json

        hit = read_json(cache, max_age_s=cfg.lrclib_cache_ttl_s)
        if hit is not None:
            logger.info("lrclib cache hit title=%r", meta.get("title"))
            return _ensure_plain_timing(hit, duration)

    params = {
        "track_name": meta.get("title"),
        "artist_name": meta.get("artist"),
        "album_name": meta.get("album"),
        "duration": round(duration, 1) if duration else None,
    }
    candidate = _get_json(f"{API_BASE}/api/get", params, cfg)
    if not _accept(candidate or {}, meta, duration):
        search_q = " ".join(p for p in (meta.get("title"), meta.get("artist")) if p)
        results = _get_json(f"{API_BASE}/api/search", {"q": search_q}, cfg)
        candidate = _pick_best(results, meta, duration)
    elif candidate is not None:
        logger.info("lrclib exact hit title=%r", meta.get("title"))

    if not isinstance(candidate, dict) or not _accept(candidate, meta, duration):
        logger.info("lrclib miss title=%r", meta.get("title"))
        return None

    t0 = time.time()
    synced = candidate.get("syncedLyrics") or ""
    lines = parse_synced_lyrics(synced) if synced else _plain_lines_even(
        (candidate.get("plainLyrics") or ""), duration
    )
    # If only an id-level record came back thin, fetch full record by id.
    if not lines and candidate.get("id"):
        full = _get_json(f"{API_BASE}/api/get/{candidate['id']}", {}, cfg)
        if isinstance(full, dict):
            candidate = full
            synced = full.get("syncedLyrics") or ""
            lines = parse_synced_lyrics(synced) if synced else []
    logger.info("lrclib %s hit title=%r lines=%d in %.1fs",
                "synced" if synced else "plain", meta.get("title"), len(lines),
                time.time() - t0)

    result = {
        "source": "lrclib_synced" if synced else "lrclib_plain",
        "lines": lines,
        "lyrics": words_even_split(lines),
        "language": None,
        "track": {
            "trackName": candidate.get("trackName"),
            "artistName": candidate.get("artistName"),
            "albumName": candidate.get("albumName"),
            "duration": candidate.get("duration"),
            "id": candidate.get("id"),
        },
    }
    from pipeline.cache import write_json

    write_json(cache, result)
    return _ensure_plain_timing(result, duration)
