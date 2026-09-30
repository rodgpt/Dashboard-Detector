"""`POST /api/devices/heartbeat` and its effect on `GET /sites/{id}/status`
(`DATA-CONTRACT.md`, **Device heartbeat**).

What matters here: a unit with no storage configured must still be observable
as alive (that is the entire reason this route exists — see TODO.md,
2026-09-23), a stale or out-of-order POST must never regress what is stored,
and the status route must prefer whichever of blob storage / Postgres is
actually fresher rather than assuming one.
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
from app.core.models import User, Device, Site, DeviceStatus, DeviceStatusHistory
from app.core.security import hash_password
from app.services.storage import get_storage

root = pathlib.Path(os.environ["OCEANKIND_LOCAL_STORAGE_ROOT"])
root.mkdir(parents=True, exist_ok=True)
if not (root / "_sites.json").exists():
    (root / "_sites.json").write_text(json.dumps({"schema_version": 2, "sites": [
        {"id": "bench", "name": "Bench", "lat": 0, "lon": 0, "device": "h", "active": True},
    ]}))

STATUS = {
    "schema_version": 2, "site": "bench", "device": "Rpi_hb",
    "generated_utc": "2026-09-23T10:00:00+00:00",
    "last_seen": "2026-09-23T10:00:00+00:00",
    "health": {"detector_ok": True, "audio_ok": True, "duty_cycle_pct": 99.2},
}


def st(**overrides):
    return {**copy.deepcopy(STATUS), **overrides}


@pytest.fixture(scope="module")
def client():
    init_db()
    SQLModel.metadata.create_all(engine())
    with Session(engine()) as db:
        if not db.exec(select(User).where(User.email == "hbadmin@x.io")).first():
            db.add(User(email="hbadmin@x.io",
                        password_hash=hash_password("correct-horse-battery"), role="admin"))
        if not db.get(Site, "bench"):
            db.add(Site(site_id="bench", name="Bench"))
        db.commit()
    c = TestClient(app)
    c.post("/api/auth/login", json={"email": "hbadmin@x.io",
                                    "password": "correct-horse-battery"})
    return c


@pytest.fixture(scope="module")
def creds(client):
    r = client.post("/api/admin/devices",
                    json={"device_id": "Rpi_hb", "site_id": "bench"})
    assert r.status_code == 201
    return {"X-Device-Id": "Rpi_hb", "X-Device-Key": r.json()["key"]}


@pytest.fixture(autouse=True)
def clean():
    with Session(engine()) as s:
        d = s.exec(select(Device).where(Device.device_id == "Rpi_hb")).first()
        if d:
            for row in s.exec(select(DeviceStatus).where(DeviceStatus.device_id == d.id)).all():
                s.delete(row)
            for row in s.exec(
                select(DeviceStatusHistory).where(DeviceStatusHistory.device_id == d.id)).all():
                s.delete(row)
        s.commit()
    storage = get_storage()
    blob = "sites/bench/status.json"
    if storage.exists(blob):
        (root / blob).unlink()
    yield


def history_count(device_id: int) -> int:
    with Session(engine()) as s:
        return len(s.exec(
            select(DeviceStatusHistory).where(DeviceStatusHistory.device_id == device_id)).all())


def device_id() -> int:
    with Session(engine()) as s:
        return s.exec(select(Device).where(Device.device_id == "Rpi_hb")).one().id


# ── acceptance ────────────────────────────────────────────────────────────────

def test_accepted_upserts_status_and_appends_history(client, creds):
    r = client.post("/api/devices/heartbeat", json=st(), headers=creds)
    assert r.status_code == 202
    assert r.json() == {"accepted": True}
    did = device_id()
    with Session(engine()) as s:
        row = s.get(DeviceStatus, did)
        assert row.payload["health"]["duty_cycle_pct"] == 99.2
    assert history_count(did) == 1


def test_newer_heartbeat_upserts_current_and_appends_second_history_row(client, creds):
    client.post("/api/devices/heartbeat", json=st(), headers=creds)
    r = client.post("/api/devices/heartbeat", headers=creds, json=st(
        generated_utc="2026-09-23T10:01:00+00:00",
        last_seen="2026-09-23T10:01:00+00:00",
        health={"detector_ok": True, "audio_ok": True, "duty_cycle_pct": 99.5}))
    assert r.status_code == 202 and r.json()["accepted"] is True
    did = device_id()
    with Session(engine()) as s:
        assert s.get(DeviceStatus, did).payload["health"]["duty_cycle_pct"] == 99.5
    assert history_count(did) == 2   # one row per heartbeat, not one per device


def test_stale_heartbeat_is_accepted_but_ignored_no_regression(client, creds):
    """The core guarantee: a late/duplicate/out-of-order POST can never
    overwrite a fresher reading, and it costs no history row either — an
    ignored heartbeat did not happen, as far as the record is concerned."""
    client.post("/api/devices/heartbeat", headers=creds,
               json=st(last_seen="2026-09-23T10:05:00+00:00"))
    did = device_id()
    r = client.post("/api/devices/heartbeat", headers=creds, json=st(
        last_seen="2026-09-23T10:00:00+00:00",   # older
        health={"detector_ok": False, "audio_ok": False, "duty_cycle_pct": 1.0}))
    assert r.status_code == 202
    assert r.json() == {"accepted": False, "reason": "stale — not newer than the stored reading"}
    with Session(engine()) as s:
        # Untouched: still the fresher reading, not the degraded one just sent.
        assert s.get(DeviceStatus, did).payload["health"]["duty_cycle_pct"] == 99.2
    assert history_count(did) == 1   # the ignored one left no trace


def test_equal_timestamp_is_also_rejected_not_just_older(client, creds):
    """The guard is `<=`, not `<` — a duplicate with the IDENTICAL timestamp
    (a device retrying after an ambiguous timeout, say) must not count as
    newer and overwrite itself with a byte-for-byte identical write that
    still costs a history row."""
    same = "2026-09-23T10:00:00+00:00"
    client.post("/api/devices/heartbeat", json=st(last_seen=same), headers=creds)
    did = device_id()
    r = client.post("/api/devices/heartbeat", json=st(last_seen=same), headers=creds)
    assert r.json() == {"accepted": False, "reason": "stale — not newer than the stored reading"}
    assert history_count(did) == 1


def test_missing_last_seen_is_400(client, creds):
    body = st(); del body["last_seen"]
    r = client.post("/api/devices/heartbeat", json=body, headers=creds)
    assert r.status_code == 400


def test_naive_last_seen_is_400(client, creds):
    r = client.post("/api/devices/heartbeat", headers=creds,
                    json=st(last_seen="2026-09-23T10:00:00"))   # no offset
    assert r.status_code == 400


def test_wrong_credentials_are_401(client):
    r = client.post("/api/devices/heartbeat", json=st(),
                    headers={"X-Device-Id": "Rpi_hb", "X-Device-Key": "wrong"})
    assert r.status_code == 401


# ── GET /sites/{id}/status: freshest-of-two-signals ────────────────────────────

def test_status_route_serves_heartbeat_when_no_blob_exists(client, creds):
    client.post("/api/devices/heartbeat", json=st(), headers=creds)
    r = client.get("/api/sites/bench/status")
    assert r.status_code == 200
    assert r.json()["health"]["duty_cycle_pct"] == 99.2
    assert "ETag" in r.headers


def test_status_route_prefers_fresher_heartbeat_over_older_blob(client, creds):
    get_storage().put("sites/bench/status.json", json.dumps(
        st(last_seen="2026-09-23T09:00:00+00:00",
          health={"duty_cycle_pct": 10.0})).encode())
    client.post("/api/devices/heartbeat", headers=creds,
               json=st(last_seen="2026-09-23T11:00:00+00:00",
                       health={"duty_cycle_pct": 88.0}))
    r = client.get("/api/sites/bench/status")
    assert r.json()["health"]["duty_cycle_pct"] == 88.0   # heartbeat is newer


def test_status_route_prefers_fresher_blob_over_older_heartbeat(client, creds):
    client.post("/api/devices/heartbeat", headers=creds,
               json=st(last_seen="2026-09-23T09:00:00+00:00",
                       health={"duty_cycle_pct": 10.0}))
    get_storage().put("sites/bench/status.json", json.dumps(
        st(last_seen="2026-09-23T11:00:00+00:00",
          health={"duty_cycle_pct": 88.0})).encode())
    r = client.get("/api/sites/bench/status")
    assert r.json()["health"]["duty_cycle_pct"] == 88.0   # blob is newer


def test_status_route_404_when_neither_source_exists(client):
    r = client.get("/api/sites/bench/status")
    assert r.status_code == 404
