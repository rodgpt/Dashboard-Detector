"""`POST /api/devices/events` — the low-latency event path (R-6.3, D-022).

The tests that matter here are the rejection paths. An accepted push is easy and
visible; a *refused* one is invisible by default, and a device whose every POST
has been refused for a week looks exactly like a quiet one. That is the failure
this route is written to make impossible, so most of what follows asserts that a
refusal is both correct and surfaced.
"""
import os, tempfile, json, pathlib

for _k, _v in {
    "OCEANKIND_SESSION_SECRET": "x" * 40,
    "OCEANKIND_STORAGE_BACKEND": "local",
    "OCEANKIND_LOCAL_STORAGE_ROOT": tempfile.mkdtemp(),
    "OCEANKIND_DB_URL": f"sqlite:///{tempfile.mktemp()}",
    "OCEANKIND_COOKIE_SECURE": "false",
    "OCEANKIND_CONFIG_HMAC_KEY": "test-signing-key-0123456789abcdef",
}.items():
    os.environ.setdefault(_k, _v)

import copy
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, select

from app.main import app
from app.core.database import init_db, engine
from app.core.models import User, DetectionEvent, Device, Site
from app.core.security import hash_password

root = pathlib.Path(os.environ["OCEANKIND_LOCAL_STORAGE_ROOT"])
root.mkdir(parents=True, exist_ok=True)
if not (root / "_sites.json").exists():
    (root / "_sites.json").write_text(json.dumps({"schema_version": 2, "sites": [
        {"id": "zapallar", "name": "Zapallar", "lat": 0, "lon": 0, "device": "a", "active": True},
        {"id": "matanzas", "name": "Matanzas", "lat": 0, "lon": 0, "device": "b", "active": True},
    ]}))


EVENT = {
    "schema_version": 2,
    "site": "zapallar",
    "device": "Rpi_push",
    "generated_utc": "2026-07-27T23:29:31.747486+00:00",
    "event_id": "aaaaaaaa-0000-4000-8000-000000000001",
    "captured_utc": "2026-07-27T23:29:31.747486+00:00",
    "uploaded_utc": "2026-07-27T23:29:44.701518+00:00",
    "event_type": "blast",
    "detector": "psd_tonal",
    "score": 0.8128,
    "suppressed": False,
    "clip": {"path": "sites/zapallar/clips/2026/07/27/x.wav", "sample_rate": 48000,
             "channels": 2, "duration_s": 5.0, "uploaded": True},
    "detector_meta": {},
}


def ev(**overrides):
    return {**copy.deepcopy(EVENT), **overrides}


@pytest.fixture(scope="module")
def client():
    init_db()
    SQLModel.metadata.create_all(engine())
    with Session(engine()) as db:
        if not db.exec(select(User).where(User.email == "pushadmin@x.io")).first():
            db.add(User(email="pushadmin@x.io",
                        password_hash=hash_password("correct-horse-battery"), role="admin"))
        for sid, name in (("zapallar", "Zapallar"), ("matanzas", "Matanzas")):
            if not db.get(Site, sid):
                db.add(Site(site_id=sid, name=name))
        db.commit()
    c = TestClient(app)
    c.post("/api/auth/login", json={"email": "pushadmin@x.io",
                                    "password": "correct-horse-battery"})
    return c


@pytest.fixture(scope="module")
def creds(client):
    r = client.post("/api/admin/devices",
                    json={"device_id": "Rpi_push", "site_id": "zapallar"})
    assert r.status_code == 201
    return {"X-Device-Id": "Rpi_push", "X-Device-Key": r.json()["key"]}


@pytest.fixture(autouse=True)
def clean_events():
    """Reset both the index and the device's push health between tests.

    The device row is module-scoped, so without clearing these a rejection
    recorded by an earlier test is still sitting there — which is the feature
    working, and makes any later "starts clean" assertion meaningless.
    """
    with Session(engine()) as s:
        for row in s.exec(select(DetectionEvent)).all():
            s.delete(row)
        d = s.exec(select(Device).where(Device.device_id == "Rpi_push")).first()
        if d:
            d.last_push_utc = d.last_push_error_utc = d.last_push_error = None
            s.add(d)
        s.commit()
    yield


def device_row() -> Device:
    with Session(engine()) as s:
        return s.exec(select(Device).where(Device.device_id == "Rpi_push")).one()


# --- the happy path ----------------------------------------------------------

def test_push_indexes_the_event(client, creds):
    r = client.post("/api/devices/events", json=EVENT, headers=creds)
    assert r.status_code == 202
    assert r.json()["indexed"] is True
    with Session(engine()) as s:
        row = s.exec(select(DetectionEvent)).one()
    assert row.event_id == EVENT["event_id"]
    assert row.first_seen_via == "push"


def test_reposting_the_same_event_is_202_not_409(client, creds):
    """A duplicate is the expected case, not an error. Returning 409 would force
    the device to track what it had successfully sent — exactly the bookkeeping
    the unique constraint exists to make unnecessary (R-12.3)."""
    assert client.post("/api/devices/events", json=EVENT, headers=creds).status_code == 202
    second = client.post("/api/devices/events", json=EVENT, headers=creds)
    assert second.status_code == 202
    assert second.json()["indexed"] is False        # already present, still success
    with Session(engine()) as s:
        assert len(s.exec(select(DetectionEvent)).all()) == 1


def test_unknown_fields_survive_the_round_trip(client, creds):
    client.post("/api/devices/events",
                json=ev(some_future_field={"a": [1, 2]}), headers=creds)
    with Session(engine()) as s:
        doc = s.exec(select(DetectionEvent)).one().document
    assert doc["some_future_field"] == {"a": [1, 2]}
    assert doc["clip"]["uploaded"] is True


# --- authentication and scoping ---------------------------------------------

def test_no_credentials_is_401_and_indexes_nothing(client):
    assert client.post("/api/devices/events", json=EVENT).status_code == 422
    r = client.post("/api/devices/events", json=EVENT,
                    headers={"X-Device-Id": "Rpi_push", "X-Device-Key": "wrong"})
    assert r.status_code == 401
    with Session(engine()) as s:
        assert s.exec(select(DetectionEvent)).all() == []


def test_site_mismatch_is_403_and_indexes_nothing(client, creds):
    """Containment: a stolen key writes to its own site or nowhere. Revocation is
    deleting the device record; this bounds the damage before anyone notices."""
    r = client.post("/api/devices/events", json=ev(site="matanzas"), headers=creds)
    assert r.status_code == 403
    assert "matanzas" in r.json()["detail"] and "zapallar" in r.json()["detail"]
    with Session(engine()) as s:
        assert s.exec(select(DetectionEvent)).all() == []


# --- the contract's timestamp rule ------------------------------------------

def test_naive_captured_utc_is_400(client, creds):
    r = client.post("/api/devices/events",
                    json=ev(captured_utc="2026-07-27T23:29:31.747486"), headers=creds)
    assert r.status_code == 400
    assert "UTC offset" in r.json()["detail"]


def test_missing_event_id_is_400(client, creds):
    bad = {k: v for k, v in EVENT.items() if k != "event_id"}
    assert client.post("/api/devices/events", json=bad, headers=creds).status_code == 400


# --- a refusal must be visible, not just returned (D-022) --------------------

def test_a_rejection_is_recorded_against_the_device(client, creds):
    """The point of the whole route. A 403 returned to an unattended box on a
    coastline is seen by nobody: our logs are unwatched and the device's own
    health surface says it is trying. So it lands next to `last_seen`, where an
    operator will see it without thinking to look."""
    before = device_row()
    assert before.last_push_error is None

    client.post("/api/devices/events", json=ev(site="matanzas"), headers=creds)

    after = device_row()
    assert after.last_push_error_utc is not None
    assert "site mismatch" in after.last_push_error


def test_a_successful_push_stamps_last_push_utc(client, creds):
    """The diagnostic is the comparison: an error stamp newer than the success
    stamp means the push path is broken right now."""
    client.post("/api/devices/events", json=EVENT, headers=creds)
    d = device_row()
    assert d.last_push_utc is not None
    assert d.last_push_error_utc is None or d.last_push_utc >= d.last_push_error_utc


def test_malformed_document_rejection_is_also_recorded(client, creds):
    client.post("/api/devices/events",
                json=ev(captured_utc="2026-07-27T23:29:31.747486"), headers=creds)
    assert "UTC offset" in device_row().last_push_error
