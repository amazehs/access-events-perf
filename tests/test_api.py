"""Functional tests for the API, run against every variant.

Performance tests say how fast; these say whether the answers are right.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.seed import seed

N_EVENTS = 300


@pytest.fixture(params=["baseline", "paginated", "optimized"])
def client(request, tmp_path):
    settings = Settings(variant=request.param, db_path=str(tmp_path / "test.db"), default_limit=50, max_limit=100)
    seed(settings, N_EVENTS)
    app = create_app(settings)
    with TestClient(app) as c:
        c.variant = request.param
        yield c
    app.state.engine.dispose()


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "variant": client.variant}


def test_get_event_by_id(client):
    r = client.get("/events/1")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == 1
    assert set(body) == {"id", "lock_id", "user_id", "event_type", "timestamp"}


def test_missing_event_returns_404(client):
    assert client.get("/events/999999").status_code == 404


def test_create_event_round_trip(client):
    payload = {"lock_id": "LOCK-0007", "user_id": "USER-00042", "event_type": "denied"}
    r = client.post("/events", json=payload)
    assert r.status_code == 201
    created = r.json()
    assert {k: created[k] for k in payload} == payload
    assert client.get(f"/events/{created['id']}").json() == created


@pytest.mark.parametrize("bad", [
    {"lock_id": "LOCK-1", "user_id": "USER-00042", "event_type": "unlock"},       # malformed lock ID
    {"lock_id": "LOCK-0007", "user_id": "bob", "event_type": "unlock"},           # malformed user ID
    {"lock_id": "LOCK-0007", "user_id": "USER-00042", "event_type": "teleport"},  # unknown type
    {"lock_id": "LOCK-0007"},                                                       # missing fields
])
def test_invalid_payload_returns_422(client, bad):
    assert client.post("/events", json=bad).status_code == 422


def test_filter_by_lock_is_exact_and_sorted(client):
    lock = client.get("/events/1").json()["lock_id"]
    body = client.get("/events", params={"lock_id": lock, "limit": 100}).json()
    assert body, "expected at least the event we read"
    assert all(e["lock_id"] == lock for e in body)
    stamps = [e["timestamp"] for e in body]
    assert stamps == sorted(stamps, reverse=True)


def test_filter_by_time_range(client):
    body = client.get("/events", params={"from": "2025-12-01T00:00:00", "to": "2025-12-15T00:00:00",
                                         "limit": 100}).json()
    assert all("2025-12-01" <= e["timestamp"][:10] < "2025-12-15" for e in body)


def test_explicit_limit_and_offset(client):
    first = client.get("/events", params={"limit": 10}).json()
    second = client.get("/events", params={"limit": 10, "offset": 10}).json()
    assert len(first) == len(second) == 10
    assert not {e["id"] for e in first} & {e["id"] for e in second}


def test_default_page_size_depends_on_variant(client):
    n = len(client.get("/events").json())
    if client.variant == "baseline":
        assert n == N_EVENTS          # the planted flaw: everything comes back
    else:
        assert n == 50                # default limit


def test_limit_is_capped_in_paginated_variants(client):
    n = len(client.get("/events", params={"limit": 1000}).json())
    assert n == (N_EVENTS if client.variant == "baseline" else 100)


def test_invalid_query_parameters(client):
    assert client.get("/events", params={"limit": 0}).status_code == 422
    assert client.get("/events", params={"lock_id": "nope"}).status_code == 422
