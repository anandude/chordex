"""GET /api/status hands back the browser's saved copy once a job has expired.

The live result lives in Redis for an hour; the library does not expire. So a
song opened from "your songs" must render even though its job is long gone —
but only for the device that saved it.
"""

import json

import pytest
from fastapi.testclient import TestClient

import library
import main

DEVICE = "0b0e5c1e-6f7a-4c2b-9d3e-8a1f2b3c4d5e"
OTHER = "ffffffff-1111-2222-3333-444444444444"
JOB = "job-expired"

PAYLOAD = {
    "chords": [{"timestamp": 0.0, "chord": "C"}],
    "key": "C",
    "tempo": 120.0,
    "duration": 60.0,
    "lyrics_status": "done",
    "sheet": {"version": 1, "beat": 0.5, "rows": []},
}


class _EmptyKV:
    """Stands in for Redis with nothing cached: every job looks expired."""

    def get(self, key):
        return None


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    # No Redis and no RQ connection in tests.
    monkeypatch.setattr(main, "_redis_kv", _EmptyKV())
    monkeypatch.setattr(main, "_fetch_job", lambda rq_id: None)
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def saved(monkeypatch):
    """A library that only answers for DEVICE; records every lookup."""
    lookups = []

    def _get_song(job_id, device_id):
        lookups.append((job_id, device_id))
        if job_id == JOB and device_id == DEVICE:
            return {"id": job_id, "payload": PAYLOAD}
        return None

    monkeypatch.setattr(library, "get_song", _get_song)
    return lookups


def test_expired_job_serves_the_owner_the_saved_copy(client, saved):
    r = client.get(f"/api/status/{JOB}", headers={"X-Device-Id": DEVICE})

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "done"
    assert body["from_library"] is True
    assert body["result"] == PAYLOAD
    assert saved == [(JOB, DEVICE)]


def test_another_device_still_gets_404(client, saved):
    r = client.get(f"/api/status/{JOB}", headers={"X-Device-Id": OTHER})
    assert r.status_code == 404


def test_no_device_header_gets_404_and_never_queries_the_library(client, saved):
    r = client.get(f"/api/status/{JOB}")
    assert r.status_code == 404
    assert saved == [], "an anonymous request must not even look up owned songs"


def test_a_malformed_device_header_is_rejected_before_the_lookup(client, saved):
    r = client.get(f"/api/status/{JOB}", headers={"X-Device-Id": "not a device"})
    assert r.status_code == 404
    assert saved == []


def test_an_unknown_job_without_a_saved_copy_is_still_404(client, saved):
    r = client.get("/api/status/job-never-existed", headers={"X-Device-Id": DEVICE})
    assert r.status_code == 404


def test_a_live_result_is_not_replaced_by_the_library(client, monkeypatch):
    calls = []

    class _KV:
        def get(self, key):
            if key == f"result:{JOB}":
                return json.dumps({"chords": [], "key": "C", "lyrics_status": "done"})
            return None

    monkeypatch.setattr(main, "_redis_kv", _KV())
    monkeypatch.setattr(
        library, "get_song", lambda *a: calls.append(a) or {"payload": PAYLOAD}
    )

    r = client.get(f"/api/status/{JOB}", headers={"X-Device-Id": DEVICE})

    body = r.json()
    assert body["from_library"] is False
    assert body["result"]["key"] == "C"
    assert calls == [], "a live job must be served from Redis, not the library"


def test_a_saved_row_without_a_payload_is_not_served(client, monkeypatch):
    monkeypatch.setattr(library, "get_song", lambda *a: {"id": JOB, "payload": None})
    r = client.get(f"/api/status/{JOB}", headers={"X-Device-Id": DEVICE})
    assert r.status_code == 404
