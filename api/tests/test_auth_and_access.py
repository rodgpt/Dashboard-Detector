"""The tests that matter: nothing leaks without a session, and a user cannot read
a site they were not assigned (R-2.1, R-3.4)."""
import os, tempfile, json, pathlib
os.environ.update({
    "OCEANKIND_SESSION_SECRET": "x" * 40,
    "OCEANKIND_STORAGE_BACKEND": "local",
    "OCEANKIND_LOCAL_STORAGE_ROOT": tempfile.mkdtemp(),
    "OCEANKIND_DB_URL": f"sqlite:///{tempfile.mktemp()}",
    "OCEANKIND_COOKIE_SECURE": "false",
    "OCEANKIND_CONFIG_SIGNING_KEY": "test-signing-key-0123456789abcdef",
})

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session
from app.main import app
from app.core.db import init_db, engine
from app.core.models import User, SiteAccess
from app.core.security import hash_password

root = pathlib.Path(os.environ["OCEANKIND_LOCAL_STORAGE_ROOT"])
(root).mkdir(parents=True, exist_ok=True)
(root / "_sites.json").write_text(json.dumps({"schema_version": 2, "sites": [
    {"id": "zapallar", "name": "Zapallar", "lat": 0, "lon": 0, "device": "a", "active": True},
    {"id": "matanzas", "name": "Matanzas", "lat": 0, "lon": 0, "device": "b", "active": True},
]}))


@pytest.fixture(scope="module")
def client():
    init_db()
    with Session(engine()) as db:
        u = User(email="op@x.io", password_hash=hash_password("correct-horse-battery"), role="operator")
        db.add(u); db.commit(); db.refresh(u)
        db.add(SiteAccess(user_id=u.id, site_id="zapallar")); db.commit()
    return TestClient(app)


def test_no_session_no_data(client):
    for path in ("/api/sites", "/api/sites/zapallar/events", "/api/sites/zapallar/status"):
        assert client.get(path).status_code == 401


def test_bad_password_rejected(client):
    r = client.post("/api/auth/login", json={"email": "op@x.io", "password": "wrong"})
    assert r.status_code == 401


def test_login_then_scoped_access(client):
    r = client.post("/api/auth/login", json={"email": "op@x.io", "password": "correct-horse-battery"})
    assert r.status_code == 200

    me = client.get("/api/auth/me").json()
    assert me["role"] == "operator" and me["sites"] == ["zapallar"]

    # only the permitted site is even listed
    assert [s["id"] for s in client.get("/api/sites").json()["sites"]] == ["zapallar"]

    # and guessing the other one's URL does not work
    assert client.get("/api/sites/matanzas/events").status_code == 403
    assert client.get("/api/sites/matanzas/status").status_code == 403


def test_admin_only_routes_closed_to_operator(client):
    assert client.get("/api/admin/users").status_code == 403


def test_logout_revokes(client):
    client.post("/api/auth/logout")
    assert client.get("/api/sites").status_code == 401


# ── device credential issuance (R-6.1, D-017) ────────────────────────────────

@pytest.fixture(scope="module")
def admin_client(client):
    with Session(engine()) as db:
        db.add(User(email="root@x.io", password_hash=hash_password("correct-horse-battery"),
                    role="admin"))
        db.commit()
    client.post("/api/auth/login", json={"email": "root@x.io", "password": "correct-horse-battery"})
    return client


def test_device_routes_closed_without_admin(client):
    # no session at all: 401. as an operator: 403, never 404.
    assert client.get("/api/admin/devices").status_code == 401
    client.post("/api/auth/login", json={"email": "op@x.io", "password": "correct-horse-battery"})
    assert client.get("/api/admin/devices").status_code == 403
    assert client.post("/api/admin/devices",
                       json={"device_id": "Rpi_x", "site_id": "zapallar"}).status_code == 403
    client.post("/api/auth/logout")


def test_issued_key_returned_once_and_never_readable_again(admin_client):
    r = admin_client.post("/api/admin/devices",
                          json={"device_id": "Rpi_zapallar", "site_id": "zapallar"})
    assert r.status_code == 201
    body = r.json()
    key = body["key"]
    assert len(key) >= 32

    # the list never exposes the key, and the hash never leaves the server
    listed = admin_client.get("/api/admin/devices").json()
    assert [d["device_id"] for d in listed] == ["Rpi_zapallar"]
    assert "key" not in listed[0] and "key_hash" not in listed[0]
    assert listed[0]["last_seen"] is None

    # the issued key authenticates the device route
    r = admin_client.get("/api/devices/config",
                         headers={"X-Device-Id": "Rpi_zapallar", "X-Device-Key": key})
    assert r.status_code == 200
    # a wrong key does not, and the error does not say which half was wrong
    r = admin_client.get("/api/devices/config",
                         headers={"X-Device-Id": "Rpi_zapallar", "X-Device-Key": "nope"})
    assert r.status_code == 401

    # the successful call stamped last_seen: provisioning feedback for the panel
    listed = admin_client.get("/api/admin/devices").json()
    assert listed[0]["last_seen"] is not None


def test_device_id_validated_and_unique(admin_client):
    assert admin_client.post("/api/admin/devices",
                             json={"device_id": "x", "site_id": "zapallar"}).status_code == 400
    assert admin_client.post("/api/admin/devices",
                             json={"device_id": "Rpi_y", "site_id": "atlantis"}).status_code == 400
    assert admin_client.post("/api/admin/devices",
                             json={"device_id": "Rpi_zapallar", "site_id": "zapallar"}).status_code == 409


def test_delete_revokes_device(admin_client):
    r = admin_client.post("/api/admin/devices",
                          json={"device_id": "Rpi_matanzas", "site_id": "matanzas"})
    key, pk = r.json()["key"], r.json()["id"]
    assert admin_client.delete(f"/api/admin/devices/{pk}").status_code == 204
    r = admin_client.get("/api/devices/config",
                         headers={"X-Device-Id": "Rpi_matanzas", "X-Device-Key": key})
    assert r.status_code == 401


# ── signed, clamped device configuration (R-6.2, F-10) ───────────────────────

@pytest.fixture(scope="module")
def cfg_device(admin_client):
    r = admin_client.post("/api/admin/devices",
                          json={"device_id": "Rpi_cfg", "site_id": "zapallar"})
    body = r.json()
    return {"pk": body["id"], "device_id": body["device_id"], "key": body["key"]}


def test_config_defaults_before_first_tune(admin_client, cfg_device):
    r = admin_client.get(f"/api/admin/devices/{cfg_device['pk']}/config")
    assert r.status_code == 200
    body = r.json()
    assert body["is_default"] is True and body["version"] == 1
    assert body["config"]["score_min"] == 0.60
    assert body["config"]["detection_mode"] == "psd"


def test_tune_clamps_and_bumps_version(admin_client, cfg_device):
    # score_min above the 0.95 bound and cooldown below the 10 s bound:
    # both clamped, both reported, nothing rejected, nothing silently accepted
    r = admin_client.put(f"/api/admin/devices/{cfg_device['pk']}/config",
                         json={"score_min": 1.5, "cooldown_s": 3, "psd_threshold_db": 12})
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == 2 and body["is_default"] is False
    assert body["config"]["score_min"] == 0.95
    assert body["config"]["cooldown_s"] == 10.0
    assert body["config"]["psd_threshold_db"] == 12.0
    assert body["config"]["alert_threshold"] == 0.08      # missing field -> default
    assert len(body["clamp_notes"]) == 2


def test_tune_rejects_what_clamping_must_not_fix(admin_client, cfg_device):
    pk = cfg_device["pk"]
    # inverted PSD band: rejected, not clamped
    assert admin_client.put(f"/api/admin/devices/{pk}/config",
                            json={"psd_f_min": 1500, "psd_f_max": 120}).status_code == 400
    # enum typo would disable detection
    assert admin_client.put(f"/api/admin/devices/{pk}/config",
                            json={"detection_mode": "pds"}).status_code == 400
    # a typo'd key that silently tuned nothing is a quiet failure
    assert admin_client.put(f"/api/admin/devices/{pk}/config",
                            json={"score_mim": 0.4}).status_code == 400
    # rejection leaves the stored config untouched
    assert admin_client.get(f"/api/admin/devices/{pk}/config").json()["version"] == 2


def test_signed_payload_verifies_and_carries_tuned_config(cfg_device):
    from fastapi.testclient import TestClient as _TC
    from app.services.deviceconfig import sign
    from app.main import app as _app
    c = _TC(_app)          # fresh client: no session cookie, credential only
    r = c.get("/api/devices/config",
              headers={"X-Device-Id": cfg_device["device_id"], "X-Device-Key": cfg_device["key"]})
    assert r.status_code == 200
    p = r.json()
    assert p["schema_version"] == 2
    assert p["device_id"] == "Rpi_cfg" and p["site"] == "zapallar"
    assert p["config_version"] == 2
    assert p["config"]["score_min"] == 0.95               # the clamped tune, in force
    assert p["expires_utc"] > p["issued_utc"]
    # the device-side check: recompute the HMAC over the canonical payload
    assert p["signature"] == sign(p, "test-signing-key-0123456789abcdef")


def test_missing_signing_key_fails_loud_never_unsigned(cfg_device):
    from app.core.config import settings
    s = settings()
    old = s.config_signing_key
    s.config_signing_key = ""
    try:
        from fastapi.testclient import TestClient as _TC
        from app.main import app as _app
        r = _TC(_app).get("/api/devices/config",
                          headers={"X-Device-Id": cfg_device["device_id"],
                                   "X-Device-Key": cfg_device["key"]})
        assert r.status_code == 503
    finally:
        s.config_signing_key = old


def test_config_routes_closed_to_operator(client, cfg_device):
    client.post("/api/auth/login", json={"email": "op@x.io", "password": "correct-horse-battery"})
    assert client.get(f"/api/admin/devices/{cfg_device['pk']}/config").status_code == 403
    assert client.put(f"/api/admin/devices/{cfg_device['pk']}/config",
                      json={"score_min": 0.1}).status_code == 403
    client.post("/api/auth/logout")
