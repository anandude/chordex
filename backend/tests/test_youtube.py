"""YouTube link handling: host allow-list and title → LRCLIB hints (offline)."""

from pathlib import Path

import pytest

import youtube
from pipeline.lyrics_lookup import get_metadata


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=VdyBtGaspss",
    "https://youtube.com/watch?v=VdyBtGaspss&list=RDx",
    "https://m.youtube.com/watch?v=VdyBtGaspss",
    "https://music.youtube.com/watch?v=VdyBtGaspss",
    "https://youtu.be/VdyBtGaspss?si=abc",
    "  https://youtu.be/VdyBtGaspss  ",
])
def test_youtube_urls_accepted(url):
    assert youtube.is_youtube_url(url)


@pytest.mark.parametrize("url", [
    "https://vimeo.com/123",
    "https://youtube.com.evil.example/watch?v=x",
    "https://evil.example/?u=https://youtube.com/watch?v=x",
    "file:///etc/passwd",
    "ftp://youtube.com/x",
    "not a url",
    "",
])
def test_other_urls_rejected(url):
    assert not youtube.is_youtube_url(url)


def test_fetch_rejects_non_youtube_before_downloading(tmp_path):
    with pytest.raises(youtube.YouTubeError):
        youtube.fetch_audio("http://127.0.0.1:8000/health", tmp_path)


def _meta(info):
    """Hints → the lyrics job's metadata, the way analyze-url wires them."""
    h = youtube.title_hints(info)
    return get_metadata(Path("audio.m4a"), h.get("title"), h.get("artist"),
                        None, filename=f"{h['name']}.m4a")


def test_label_upload_with_film_and_cast():
    m = _meta({"title": "Chahun Main Ya Naa Full Video Song Aashiqui 2 | "
                        "Aditya Roy Kapur, Shraddha Kapoor", "channel": "T-Series"})
    assert m == {"title": "Chahun Main Ya Naa"}


def test_pipe_separated_credits():
    m = _meta({"title": "Mazha Njaan Arinjirunnilla | Dr. Patient | Hariharan | "
                        "Bennet Veetraag | Rafeeq Ahammed",
               "channel": "Sony Music Malayalam"})
    assert m == {"title": "Mazha Njaan Arinjirunnilla"}


def test_artist_dash_title_with_official_tag():
    m = _meta({"title": "Elvis Presley - Can't Help Falling In Love (Official Audio)",
               "channel": "Elvis Presley"})
    assert m == {"artist": "Elvis Presley", "title": "Can't Help Falling In Love"}


def test_topic_channel_gives_explicit_artist():
    h = youtube.title_hints({"title": "Tum Hi Ho", "channel": "Arijit Singh - Topic"})
    assert h == {"name": "Arijit Singh - Tum Hi Ho", "title": "Tum Hi Ho",
                 "artist": "Arijit Singh"}


def test_music_metadata_wins_over_title():
    h = youtube.title_hints({"title": "SONG (Lyric Video) | whatever",
                             "track": "Song", "artist": "A, B"})
    assert h["title"] == "Song" and h["artist"] == "A"


def test_empty_title_has_a_name():
    assert youtube.title_hints({})["name"] == "youtube"


# ── server-side bot challenges (datacenter IPs) ───────────────────────────

_BOT = (
    "ERROR: [youtube] VdyBtGaspss: Sign in to confirm you're not a bot. "
    "Use --cookies-from-browser or --cookies for the authentication."
)


class _FakeDownloadError(Exception):
    pass


def _install_fake_yt_dlp(monkeypatch, attempts):
    """Install a fake ``yt_dlp`` whose n-th call follows ``attempts[n]``.

    Each entry is ``("error", "message")`` or ``("ok", info_dict)``. Returns the
    option dicts actually used, in order, so a test can assert what was tried.
    """
    import sys
    import types

    calls: list[dict] = []

    class YoutubeDL:
        def __init__(self, opts):
            self.opts = opts
            calls.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=True):
            kind, payload = attempts[len(calls) - 1]
            if kind == "error":
                raise _FakeDownloadError(payload)
            outtmpl = self.opts["outtmpl"]
            Path(outtmpl.replace("%(ext)s", "m4a")).write_bytes(b"audio")
            return payload

    monkeypatch.setitem(
        sys.modules,
        "yt_dlp",
        types.SimpleNamespace(
            YoutubeDL=YoutubeDL,
            utils=types.SimpleNamespace(DownloadError=_FakeDownloadError),
        ),
    )
    return calls


def test_bot_challenge_retries_with_the_next_client(monkeypatch, tmp_path):
    monkeypatch.setenv("YOUTUBE_PLAYER_CLIENTS", "android_vr,ios")
    calls = _install_fake_yt_dlp(monkeypatch, [
        ("error", _BOT),
        ("ok", {"title": "Song", "channel": "Artist - Topic", "duration": 200}),
    ])

    path, hints = youtube.fetch_audio("https://youtu.be/VdyBtGaspss", tmp_path)

    assert path.exists()
    assert hints["name"] == "Artist - Song"
    assert len(calls) == 2
    assert "extractor_args" not in calls[0]  # default client first
    assert calls[1]["extractor_args"] == {"youtube": {"player_client": ["android_vr"]}}


def test_bot_challenge_on_every_client_is_a_friendly_error(monkeypatch, tmp_path):
    monkeypatch.setenv("YOUTUBE_PLAYER_CLIENTS", "android_vr,ios")
    calls = _install_fake_yt_dlp(monkeypatch, [("error", _BOT)] * 3)

    with pytest.raises(youtube.YouTubeError) as exc:
        youtube.fetch_audio("https://youtu.be/VdyBtGaspss", tmp_path)

    assert str(exc.value) == youtube._BLOCKED_MESSAGE
    assert len(calls) == 3  # default + the two configured clients


def test_a_real_error_is_not_retried(monkeypatch, tmp_path):
    monkeypatch.setenv("YOUTUBE_PLAYER_CLIENTS", "android_vr,ios")
    calls = _install_fake_yt_dlp(monkeypatch, [
        ("error", "ERROR: [youtube] VdyBtGaspss: Video unavailable"),
    ])

    with pytest.raises(youtube.YouTubeError) as exc:
        youtube.fetch_audio("https://youtu.be/VdyBtGaspss", tmp_path)

    assert "Video unavailable" in str(exc.value)
    assert len(calls) == 1


def test_cookies_and_proxy_are_passed_through(monkeypatch, tmp_path):
    monkeypatch.setenv("YOUTUBE_COOKIES_FILE", "/run/secrets/cookies.txt")
    monkeypatch.setenv("YOUTUBE_PROXY", "http://proxy.example:8080")
    monkeypatch.setenv("YOUTUBE_PLAYER_CLIENTS", "")
    calls = _install_fake_yt_dlp(monkeypatch, [
        ("ok", {"title": "Song", "channel": "Artist"}),
    ])

    youtube.fetch_audio("https://youtu.be/VdyBtGaspss", tmp_path)

    assert calls[0]["cookiefile"] == "/run/secrets/cookies.txt"
    assert calls[0]["proxy"] == "http://proxy.example:8080"


def test_player_client_list_can_be_overridden(monkeypatch):
    monkeypatch.setenv("YOUTUBE_PLAYER_CLIENTS", " android_vr , ,ios ")
    assert youtube._player_clients() == ("android_vr", "ios")
    monkeypatch.delenv("YOUTUBE_PLAYER_CLIENTS")
    assert youtube._player_clients() == youtube._DEFAULT_PLAYER_CLIENTS


def test_clean_error_strips_the_ytdlp_prefix():
    assert youtube._clean_error(Exception(_BOT)).startswith("Sign in to confirm")

