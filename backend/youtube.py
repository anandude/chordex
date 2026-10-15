"""
youtube.py
----------
Fetch a song's audio from a YouTube link (personal use) so it can go through
the same pipeline as an upload.

Only YouTube hosts are accepted — yt-dlp can fetch from thousands of sites,
and the API should not become a general URL fetcher. Playlists are ignored
(the single video in ``?v=`` is used) and long videos are refused before any
bytes are downloaded.

Public API:
    is_youtube_url(url) -> bool
    fetch_audio(url, dest_dir) -> (path, hints)
    title_hints(info) -> dict   # display name + LRCLIB title/artist hints
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlparse

_YT_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
    "youtu.be", "www.youtu.be",
}
MAX_DURATION_S = int(os.getenv("YOUTUBE_MAX_DURATION_S", "1200"))  # 20 min


class YouTubeError(Exception):
    """User-facing failure (bad link, unavailable video, too long)."""


def is_youtube_url(url: str) -> bool:
    try:
        p = urlparse(url.strip())
    except ValueError:
        return False
    return p.scheme in ("http", "https") and (p.hostname or "").lower() in _YT_HOSTS


# ── title → LRCLIB hints ──────────────────────────────────────────────────
# Label uploads pack everything into the title:
#   "Chahun Main Ya Naa Full Video Song Aashiqui 2 | Aditya Roy Kapur, ..."
#   "Mazha Njaan Arinjirunnilla | Dr. Patient | Hariharan | ..."
#   "Elvis Presley - Can't Help Falling In Love (Official Audio)"

# Bracketed tags that are never part of a song title.
_BRACKET_NOISE = re.compile(
    r"[(\[][^)\]]*\b(official|video|audio|lyrics?|lyrical|visuali[sz]er|hd|4k|"
    r"remaster(ed)?|full song|song|m/?v)\b[^)\]]*[)\]]",
    re.IGNORECASE,
)
# "... Full Video Song Aashiqui 2" — everything from the tag on is film/cast.
_TAIL_NOISE = re.compile(
    r"\s+(\(?\s*)?(full|official|lyric(al)?|video|audio)\s+"
    r"(video\s+|audio\s+|lyric(al)?\s+)?(song|video|audio)\b.*$",
    re.IGNORECASE,
)


def _clean_title(title: str) -> str:
    title = title.split(" | ")[0].split("｜")[0]
    title = _BRACKET_NOISE.sub(" ", title)
    title = _TAIL_NOISE.sub("", title)
    return re.sub(r"\s+", " ", title).strip(" -–—|:")


def title_hints(info: dict) -> dict:
    """``{"name": "Artist - Title", "title": ..., "artist": ...}``.

    Explicit music metadata (YouTube Music / auto-generated "Topic" channels)
    wins; otherwise the title is cleaned and the existing filename heuristics
    (``Artist - Title``) take it from there. ``title``/``artist`` are only set
    when the metadata is explicit, so a guessed artist never overrides them.
    """
    track = (info.get("track") or "").strip()
    artist = (info.get("artist") or info.get("creator") or "").strip()
    channel = (info.get("channel") or info.get("uploader") or "").strip()
    if not artist and channel.endswith(" - Topic"):
        artist = channel[: -len(" - Topic")].strip()
        track = track or (info.get("title") or "").strip()
    if track and artist:
        artist = artist.split(",")[0].strip()
        return {"name": f"{artist} - {track}", "title": track, "artist": artist}
    name = _clean_title(info.get("title") or "") or "youtube"
    return {"name": name}


# ── download ──────────────────────────────────────────────────────────────

def fetch_audio(url: str, dest_dir: Path) -> tuple[Path, dict]:
    """Download the best audio-only stream as m4a into ``dest_dir``.

    Returns the file path and ``title_hints`` for the video. Raises
    ``YouTubeError`` with a message suitable for the UI.
    """
    if not is_youtube_url(url):
        raise YouTubeError("Only YouTube links are supported.")
    import yt_dlp

    def _too_long(info: dict, *, incomplete: bool) -> str | None:
        dur = info.get("duration")
        if info.get("is_live"):
            return "Live streams can't be analysed."
        if dur and dur > MAX_DURATION_S:
            return f"Video is too long ({dur // 60} min; max {MAX_DURATION_S // 60} min)."
        return None

    dest_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        # m4a (AAC) is usually offered directly; anything else is remuxed or
        # transcoded by ffmpeg below. Both librosa and browsers play m4a.
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": str(dest_dir / "audio.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "match_filter": _too_long,
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "m4a"}],
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url.strip(), download=True)
    except yt_dlp.utils.DownloadError as exc:
        msg = re.sub(r"^ERROR:\s*(\[[^\]]+\]\s*[\w-]+:\s*)?", "", str(exc)).strip()
        raise YouTubeError(f"Couldn't fetch that video: {msg}") from exc

    if not info:
        raise YouTubeError("Couldn't fetch that video.")
    if info.get("_type") == "playlist" or "entries" in info:
        raise YouTubeError("Paste a link to a single video, not a playlist.")
    reason = _too_long(info, incomplete=False)
    if reason:
        raise YouTubeError(reason)

    files = sorted(dest_dir.glob("audio.*"))
    if not files:
        # match_filter skips (too long / live) download nothing
        raise YouTubeError(reason or "Video was skipped (too long or live?).")
    return files[0], title_hints(info)
