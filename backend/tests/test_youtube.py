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
