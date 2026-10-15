"""Unit tests for storage.py (local filesystem mode)."""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Force local mode before import side effects re-read env in functions
os.environ.pop("S3_BUCKET", None)


def test_save_resolve_cleanup(tmp_path, monkeypatch):
    import storage

    monkeypatch.setattr(storage, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(storage, "_S3_BUCKET", "")

    uri = storage.save_upload("job-abc", b"fake-audio-bytes", "wav")
    assert uri.startswith("file://")
    path = storage.resolve_path(uri)
    assert Path(path).read_bytes() == b"fake-audio-bytes"
    assert storage.get_content_type(uri) == "audio/wav"

    found = storage.uri_for_job("job-abc")
    assert found == uri

    storage.cleanup(uri)
    assert not Path(path).exists()


def test_audio_byte_range_parsing():
    from main import _byte_range

    assert _byte_range("bytes=0-99", 1000) == (0, 99)
    assert _byte_range("bytes=900-", 1000) == (900, 999)
    assert _byte_range("bytes=-100", 1000) == (900, 999)
    assert _byte_range("bytes=0-5000", 1000) == (0, 999)
    assert _byte_range("bytes=2000-", 1000) is None
    assert _byte_range("bytes=0-1,5-6", 1000) is None
    assert _byte_range(None, 1000) is None
