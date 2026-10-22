"""Song library: device scoping, payload shape, and graceful no-op behaviour.

No database is involved: a fake pool records the SQL and parameters each call
issues, which is exactly what the security property (one device can never read
or overwrite another's songs) depends on.
"""

import json
from datetime import datetime, timezone

import pytest

import library

DEVICE = "0b0e5c1e-6f7a-4c2b-9d3e-8a1f2b3c4d5e"


class _FakeCursor:
    def __init__(self, pool):
        self.pool = pool
        self.rowcount = pool.rowcount

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.pool.queries.append((sql, params))

    def fetchall(self):
        return self.pool.rows

    def fetchone(self):
        return self.pool.rows[0] if self.pool.rows else None


class _FakeConnection:
    def __init__(self, pool):
        self.pool = pool

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self, row_factory=None):
        return _FakeCursor(self.pool)


class _FakePool:
    def __init__(self, rows=None, rowcount=0):
        self.rows = rows or []
        self.rowcount = rowcount
        self.queries = []

    def connection(self):
        return _FakeConnection(self)


@pytest.fixture
def db(monkeypatch):
    """A configured library backed by a recording fake pool."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/chordex")
    pool = _FakePool()
    monkeypatch.setattr(library, "_pool", pool)
    return pool


# ── device ids ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value,ok", [
    (DEVICE, True),
    ("abcdefgh", True),
    ("A_b-C_d-9", True),
    ("abc", False),
    ("", False),
    (None, False),
    ("has space", False),
    ("semi;colon", False),
    ("quote'", False),
    ("a" * 65, False),
])
def test_device_id_validation(value, ok):
    assert library.valid_device_id(value) is ok


# ── unconfigured: every call is a no-op ───────────────────────────────────

def test_disabled_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert library.enabled() is False
    assert library.save("job-1", DEVICE, {"chords": []}) is False
    assert library.list_songs(DEVICE) == []
    assert library.get_song("job-1", DEVICE) is None
    assert library.delete_song("job-1", DEVICE) is False
    assert library.init() is None  # must not raise


def test_blank_database_url_counts_as_disabled(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "   ")
    assert library.enabled() is False


# ── save ──────────────────────────────────────────────────────────────────

def test_save_writes_the_owner_and_the_full_payload(db):
    result = {
        "source_name": "Arijit Singh - Tum Hi Ho",
        "artist": "Arijit Singh",
        "key": "Am",
        "tempo": 92.5,
        "duration": 261.0,
        "engine": "chordino",
        "lyrics_status": "done",
        "lyrics_source": "asr",
        "chords": [{"chord": "Am"}, {"chord": "F"}],
        "lyrics": [{"word": "tum"}],
        "sheet": {"version": 1, "rows": []},
    }

    assert library.save("job-1", DEVICE, result) is True

    sql, params = db.queries[0]
    assert "INSERT INTO chordex_songs" in sql
    # The upsert must not be able to reassign a row to another device.
    assert "WHERE chordex_songs.device_id = EXCLUDED.device_id" in sql
    assert "device_id       = EXCLUDED" not in sql
    assert params["device_id"] == DEVICE
    assert params["song_key"] == "Am"
    assert params["n_chords"] == 2
    assert params["has_lyrics"] is True
    assert json.loads(params["payload"])["sheet"] == {"version": 1, "rows": []}


def test_save_rejects_an_invalid_device_id(db):
    assert library.save("job-1", "not a device", {"chords": []}) is False
    assert db.queries == []


def test_save_refuses_a_payload_that_is_not_json(db):
    assert library.save("job-1", DEVICE, {"chords": {1, 2}}) is False
    assert db.queries == []


def test_save_swallows_store_errors(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/chordex")

    class _Broken:
        def connection(self):
            raise RuntimeError("neon is asleep")

    monkeypatch.setattr(library, "_pool", _Broken())
    assert library.save("job-1", DEVICE, {"chords": []}) is False


# ── list / get / delete ───────────────────────────────────────────────────

def _row(**over):
    row = {
        "id": "job-1",
        "created_at": datetime(2026, 10, 22, 9, 30, tzinfo=timezone.utc),
        "source_name": "Artist - Song",
        "artist": "Artist",
        "lyrics_language": "ml",
        "duration": 201.0,
        "song_key": "Am",
        "tempo": 88.0,
        "engine": "chordino",
        "lyrics_status": "done",
        "lyrics_source": "lrclib_synced",
        "n_chords": 14,
        "has_lyrics": True,
    }
    row.update(over)
    return row


def test_list_is_device_scoped_and_maps_key_names(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/chordex")
    pool = _FakePool(rows=[_row()])
    monkeypatch.setattr(library, "_pool", pool)

    songs = library.list_songs(DEVICE, limit=10)

    sql, params = pool.queries[0]
    assert "WHERE device_id = %s" in sql
    assert params == (DEVICE, 10)
    assert songs[0]["key"] == "Am"          # song_key → key for the client
    assert songs[0]["created_at"].startswith("2026-10-22T09:30")
    assert songs[0]["n_chords"] == 14
    assert "payload" not in songs[0]        # the list stays light


def test_list_clamps_the_limit(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/chordex")
    pool = _FakePool()
    monkeypatch.setattr(library, "_pool", pool)

    library.list_songs(DEVICE, limit=99_999)
    assert pool.queries[0][1] == (DEVICE, 200)


def test_get_scopes_by_job_and_device(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/chordex")
    pool = _FakePool(rows=[_row(payload={"version": 1, "rows": [], "beat": 0.5})])
    monkeypatch.setattr(library, "_pool", pool)

    song = library.get_song("job-1", DEVICE)

    sql, params = pool.queries[0]
    assert "WHERE id = %s AND device_id = %s" in sql
    assert params == ("job-1", DEVICE)
    assert song["payload"]["beat"] == 0.5


def test_get_returns_none_for_someone_elses_song(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/chordex")
    monkeypatch.setattr(library, "_pool", _FakePool(rows=[]))
    assert library.get_song("job-1", DEVICE) is None


def test_delete_reports_whether_a_row_went(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/chordex")

    pool = _FakePool(rowcount=1)
    monkeypatch.setattr(library, "_pool", pool)
    assert library.delete_song("job-1", DEVICE) is True
    sql, params = pool.queries[0]
    assert "WHERE id = %s AND device_id = %s" in sql
    assert params == ("job-1", DEVICE)

    monkeypatch.setattr(library, "_pool", _FakePool(rowcount=0))
    assert library.delete_song("job-1", DEVICE) is False


# ── init ──────────────────────────────────────────────────────────────────

def test_init_creates_schema_when_configured(db):
    assert library.init() is None
    statements = [sql for sql, _ in db.queries]
    assert any("CREATE TABLE IF NOT EXISTS chordex_songs" in s for s in statements)
    assert any("CREATE INDEX IF NOT EXISTS" in s for s in statements)
