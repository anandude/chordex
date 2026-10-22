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

import logging
import os
import re
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_YT_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
    "youtu.be", "www.youtu.be",
}
MAX_DURATION_S = int(os.getenv("YOUTUBE_MAX_DURATION_S", "1200"))  # 20 min

# ── server-side bot challenges ────────────────────────────────────────────
# YouTube challenges datacenter IPs (the deployed InstaBox box included) with
# "Sign in to confirm you're not a bot". It serves different player clients
# different trust levels, so when the default attempt is challenged the same
# video often still comes through on another client. Tried in order, after the
# default attempt; override with YOUTUBE_PLAYER_CLIENTS (comma-separated, an
# empty value disables the retries).
_DEFAULT_PLAYER_CLIENTS = ("android_vr", "ios", "tv", "mweb", "web_safari")

#: Messages that mean "YouTube wants a signed-in session" — worth retrying with
#: another client. Anything else (private, removed, too long) is a real answer
#: and is reported straight away instead of being retried four more times.
_CHALLENGE_HINTS = re.compile(
    r"sign in to confirm|not a bot|confirm your age|age[- ]restricted"
    r"|sign[- ]in required|requires? (?:authentication|sign[- ]in)"
    r"|http error 403|cookies for the authentication",
    re.IGNORECASE,
)

#: Shown in the UI when every client is refused. Uploading the file always
#: works, so point at that rather than leaking a yt-dlp stack message.
_BLOCKED_MESSAGE = (
    "YouTube is blocking downloads from this server (it asks for a sign-in). "
    "Upload the audio file instead — that always works."
)


def _player_clients() -> tuple[str, ...]:
    raw = os.getenv("YOUTUBE_PLAYER_CLIENTS")
    if raw is None:
        return _DEFAULT_PLAYER_CLIENTS
    return tuple(c.strip() for c in raw.split(",") if c.strip())


def _clean_error(exc: Exception) -> str:
    """Strip yt-dlp's ``ERROR: [youtube] ID:`` prefix to the useful sentence."""
    return re.sub(
        r"^ERROR:\s*(\[[^\]]+\]\s*[\w-]+:\s*)?", "", str(exc)
    ).strip()


class YouTubeError(Exception):
    """User-facing failure (bad link, unavailable video, too long)."""


def _as_error(message: str) -> YouTubeError:
    """Wrap a cleaned yt-dlp message; our own filter messages stand alone."""
    if message.startswith(("Video is too long", "Live streams")):
        return YouTubeError(message)
    return YouTubeError(f"Couldn't fetch that video: {message}")


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

    Tries the default player client first, then the clients in
    ``YOUTUBE_PLAYER_CLIENTS`` — YouTube challenges datacenter IPs ("Sign in to
    confirm you're not a bot") per client, so one of them usually still serves
    the stream. ``YOUTUBE_COOKIES_FILE`` (a Netscape ``cookies.txt``) and
    ``YOUTUBE_PROXY`` are passed through when set, which are the escape hatches
    when every client is refused.

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

    cookies = os.getenv("YOUTUBE_COOKIES_FILE", "").strip()
    proxy = os.getenv("YOUTUBE_PROXY", "").strip()

    def _opts(client: str | None) -> dict:
        opts: dict = {
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
        if client:
            opts["extractor_args"] = {"youtube": {"player_client": [client]}}
        if cookies:
            opts["cookiefile"] = cookies
        if proxy:
            opts["proxy"] = proxy
        return opts

    dest_dir.mkdir(parents=True, exist_ok=True)
    attempts: tuple[str | None, ...] = (None, *_player_clients())
    info: dict | None = None
    for i, client in enumerate(attempts):
        if i:  # a challenged attempt can leave a partial download behind
            for stale in dest_dir.glob("audio.*"):
                stale.unlink(missing_ok=True)
        try:
            with yt_dlp.YoutubeDL(_opts(client)) as ydl:
                info = ydl.extract_info(url.strip(), download=True)
            break
        except yt_dlp.utils.DownloadError as exc:
            msg = _clean_error(exc)
            if not _CHALLENGE_HINTS.search(msg):
                # Private, removed, too long… a real answer: don't retry it.
                raise _as_error(msg) from exc
            if i == len(attempts) - 1:
                logger.warning(
                    "youtube refused %s for every client (%s): %s",
                    url, ", ".join(c or "default" for c in attempts), msg,
                )
                raise YouTubeError(_BLOCKED_MESSAGE) from exc
            logger.info(
                "youtube challenged client %s for %s; retrying with %s",
                client or "default", url, attempts[i + 1] or "default",
            )

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
