"""The tests that matter: nothing leaks without a session, and a user cannot read
a site they were not assigned (R-2.1, R-3.4)."""
import os, tempfile, json, pathlib
os.environ.update({
    "OCEANKIND_SESSION_SECRET": "x" * 40,
    "OCEANKIND_STORAGE_BACKEND": "local",
    "OCEANKIND_LOCAL_STORAGE_ROOT": tempfile.mkdtemp(),
    "OCEANKIND_DB_URL": f"sqlite:///{tempfile.mktemp()}",
    "OCEANKIND_COOKIE_SECURE": "false",
    "OCEANKIND_CONFIG_HMAC_KEY": "test-signing-key-0123456789abcdef",
})

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session
from app.main import app
from app.core.database import init_db, engine
from app.core.models import User, SiteAccess
from app.core.security import hash_password, derive_keys

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
    secret = body["key"]
    assert len(secret) >= 32
    # one secret, two derived keys (D-020): the device presents the auth key
    key, _config_key = derive_keys(secret)

    # the list never exposes the secret or either key, and the hash never leaves the server
    listed = admin_client.get("/api/admin/devices").json()
    assert [d["device_id"] for d in listed] == ["Rpi_zapallar"]
    assert "key" not in listed[0] and "key_hash" not in listed[0] and "config_key" not in listed[0]
    assert listed[0]["last_seen"] is None
    assert listed[0]["needs_reprovision"] is False

    # the secret itself is NOT the credential on the wire
    r = admin_client.get("/api/devices/config",
                         headers={"X-Device-Id": "Rpi_zapallar", "X-Device-Key": secret})
    assert r.status_code == 401
    # the derived key authenticates the device route. 404 because nothing has been
    # published for this device yet — that is the honest answer, not a fabricated doc
    r = admin_client.get("/api/devices/config",
                         headers={"X-Device-Id": "Rpi_zapallar", "X-Device-Key": key})
    assert r.status_code == 404
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
    key, pk = derive_keys(r.json()["key"])[0], r.json()["id"]
    assert admin_client.delete(f"/api/admin/devices/{pk}").status_code == 204
    r = admin_client.get("/api/devices/config",
                         headers={"X-Device-Id": "Rpi_matanzas", "X-Device-Key": key})
    assert r.status_code == 401


def test_delete_device_that_has_heartbeated(admin_client):
    """device_status and device_status_history carry a FK to device.id with no
    cascade (heartbeat migration). A device that has reported in at least once
    — i.e. any real device — must still be deletable, not just a freshly
    created one that never connected."""
    r = admin_client.post("/api/admin/devices",
                          json={"device_id": "Rpi_matanzas_hb", "site_id": "matanzas"})
    key, pk = derive_keys(r.json()["key"])[0], r.json()["id"]
    creds = {"X-Device-Id": "Rpi_matanzas_hb", "X-Device-Key": key}
    hb = admin_client.post("/api/devices/heartbeat", headers=creds, json={
        "schema_version": 2, "site": "matanzas", "device": "Rpi_matanzas_hb",
        "generated_utc": "2026-09-23T10:00:00+00:00",
        "last_seen": "2026-09-23T10:00:00+00:00",
        "health": {"detector_ok": True, "audio_ok": True, "duty_cycle_pct": 99.2},
    })
    assert hb.status_code == 202
    assert admin_client.delete(f"/api/admin/devices/{pk}").status_code == 204


# ── signed, clamped device configuration (R-6.2, F-10) ───────────────────────

@pytest.fixture(scope="module")
def cfg_device(admin_client):
    r = admin_client.post("/api/admin/devices",
                          json={"device_id": "Rpi_cfg", "site_id": "zapallar"})
    body = r.json()
    auth_key, config_key = derive_keys(body["key"])
    return {"pk": body["id"], "device_id": body["device_id"], "secret": body["key"],
            "key": auth_key, "config_key": config_key}


def test_config_defaults_before_first_tune(admin_client, cfg_device):
    r = admin_client.get(f"/api/admin/devices/{cfg_device['pk']}/config")
    assert r.status_code == 200
    body = r.json()
    assert body["is_default"] is True and body["config_version"] == "default"
    assert body["config"]["score_min"] == 0.60
    assert body["config"]["detection_mode"] == "psd"
    assert body["config"]["window_hop_s"] == 5.0        # tenth key, contract 2026-08-22


def test_tune_clamps_and_publishes_the_blob(admin_client, cfg_device):
    # score_min above the 0.95 bound and cooldown below the 10 s bound:
    # both clamped, both reported, nothing rejected, nothing silently accepted
    r = admin_client.put(f"/api/admin/devices/{cfg_device['pk']}/config",
                         json={"score_min": 1.5, "cooldown_s": 3, "psd_threshold_db": 12})
    assert r.status_code == 200
    body = r.json()
    assert body["is_default"] is False
    assert body["config"]["score_min"] == 0.95
    assert body["config"]["cooldown_s"] == 10.0
    assert body["config"]["psd_threshold_db"] == 12.0
    assert body["config"]["alert_threshold"] == 0.08      # missing field -> default
    assert len(body["clamp_notes"]) == 2
    # transport is storage, so a tune that did not reach a blob did not happen
    assert body["published_to"] == "sites/zapallar/remote_config.json"
    # zapallar also holds Rpi_zapallar, and a site has exactly one config blob.
    # Overwriting it silently is the failure mode; saying so is the fix.
    assert body["publish_warning"] is not None
    assert "Rpi_zapallar" in body["publish_warning"]


def test_published_blob_is_the_contract_document_and_verifies(admin_client, cfg_device):
    """The device's own check, done here: read the blob, recompute the HMAC over
    the whole document minus `signature`, compare."""
    from app.services.storage import get_storage
    from app.services.deviceconfig import sign
    import json as _json

    raw = get_storage().get("sites/zapallar/remote_config.json")
    doc = _json.loads(raw)

    assert doc["schema_version"] == 2
    assert doc["site"] == "zapallar"
    assert doc["device_id"] == "Rpi_cfg"          # the device whose key signed it
    assert isinstance(doc["config_version"], str) and doc["config_version"] != "default"
    assert "expires_utc" not in doc               # there is no expiry (D-020)
    assert doc["config"]["score_min"] == 0.95     # the clamped value is what ships
    # release assignment rides inside config (Rpi-Detector D-021); none yet
    assert doc["config"]["release"] is None and doc["config"]["hold"] is False
    # signed with THIS device's derived key, not a global one (Rpi-Detector D-020)
    assert doc["signature"] == sign(doc, cfg_device["config_key"])
    assert doc["signature"] != sign(doc, "test-signing-key-0123456789abcdef")


def test_debug_view_returns_the_blob_byte_for_byte(admin_client, cfg_device):
    """Two ways to read the same document must never differ; that is exactly how
    a signature mismatch would hide."""
    from app.services.storage import get_storage
    from fastapi.testclient import TestClient as _TC
    from app.main import app as _app

    r = _TC(_app).get("/api/devices/config",
                      headers={"X-Device-Id": cfg_device["device_id"],
                               "X-Device-Key": cfg_device["key"]})
    assert r.status_code == 200
    assert r.content == get_storage().get("sites/zapallar/remote_config.json")


def test_config_version_changes_on_every_tune(admin_client, cfg_device):
    first = admin_client.get(f"/api/admin/devices/{cfg_device['pk']}/config").json()["config_version"]
    admin_client.put(f"/api/admin/devices/{cfg_device['pk']}/config", json={"score_min": 0.5})
    second = admin_client.get(f"/api/admin/devices/{cfg_device['pk']}/config").json()["config_version"]
    assert first != second


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
    # window_hop_s is clamped, not rejected
    r = admin_client.put(f"/api/admin/devices/{pk}/config", json={"window_hop_s": 0.1})
    assert r.status_code == 200 and r.json()["config"]["window_hop_s"] == 1.0


def test_device_without_signing_key_cannot_be_configured(admin_client, cfg_device):
    """A device created before D-020 has no per-device key. Refuse to sign (409,
    naming the fix) rather than sign with a key the unit does not hold, and
    never publish unsigned. The panel flags it as `needs_reprovision`."""
    from app.core.models import Device
    with Session(engine()) as db:
        d = db.get(Device, cfg_device["pk"])
        old = d.config_key
        d.config_key = None
        db.add(d); db.commit()
    try:
        r = admin_client.put(f"/api/admin/devices/{cfg_device['pk']}/config",
                             json={"score_min": 0.7})
        assert r.status_code == 409 and "re" in r.json()["detail"].lower()
        r = admin_client.put(f"/api/admin/devices/{cfg_device['pk']}/release",
                             json={"release": "v2.2.0"})
        assert r.status_code == 409
        listed = {d["device_id"]: d for d in admin_client.get("/api/admin/devices").json()}
        assert listed["Rpi_cfg"]["needs_reprovision"] is True
        # and the device itself is told, not handed a document it cannot verify
        from fastapi.testclient import TestClient as _TC
        from app.main import app as _app
        r = _TC(_app).get("/api/devices/config",
                          headers={"X-Device-Id": cfg_device["device_id"],
                                   "X-Device-Key": cfg_device["key"]})
        assert r.status_code == 409
    finally:
        with Session(engine()) as db:
            d = db.get(Device, cfg_device["pk"])
            d.config_key = old
            db.add(d); db.commit()


# ── assigned releases (Rpi-Detector D-021) ───────────────────────────────────

def test_assign_release_resigns_and_republishes(admin_client, cfg_device):
    from app.services.deviceconfig import sign
    import json as _json
    pk = cfg_device["pk"]
    before = admin_client.get(f"/api/admin/devices/{pk}/config").json()
    r = admin_client.put(f"/api/admin/devices/{pk}/release", json={"release": "v2.2.0"})
    assert r.status_code == 200
    body = r.json()
    assert body["release"] == "v2.2.0" and body["hold"] is False
    assert body["config_version"] != before["config_version"]   # the unit sees a new version
    assert body["config"] == before["config"]                    # thresholds untouched
    # the device route serves exactly the re-signed document
    from fastapi.testclient import TestClient as _TC
    from app.main import app as _app
    r = _TC(_app).get("/api/devices/config",
                      headers={"X-Device-Id": cfg_device["device_id"],
                               "X-Device-Key": cfg_device["key"]})
    doc = _json.loads(r.content)
    assert doc["config"]["release"] == "v2.2.0" and doc["config"]["hold"] is False
    assert doc["signature"] == sign(doc, cfg_device["config_key"])
    # hold alone, release kept
    r = admin_client.put(f"/api/admin/devices/{pk}/release", json={"hold": True})
    assert r.json()["hold"] is True and r.json()["release"] == "v2.2.0"
    # a tag that is not a tag is refused
    assert admin_client.put(f"/api/admin/devices/{pk}/release",
                            json={"release": "main; rm -rf /"}).status_code == 400
    # the panel lists it
    listed = {d["device_id"]: d for d in admin_client.get("/api/admin/devices").json()}
    assert listed["Rpi_cfg"]["assigned_release"] == "v2.2.0" and listed["Rpi_cfg"]["hold"] is True
    # clearing the assignment
    r = admin_client.put(f"/api/admin/devices/{pk}/release", json={"release": None, "hold": False})
    assert r.json()["release"] is None


def test_tune_cannot_smuggle_release_keys(admin_client, cfg_device):
    """`release`/`hold` are set through the release route; a tune that submits
    them is not an error (the form may echo the config back) but does not
    change the assignment."""
    pk = cfg_device["pk"]
    admin_client.put(f"/api/admin/devices/{pk}/release", json={"release": "v2.2.1"})
    r = admin_client.put(f"/api/admin/devices/{pk}/config",
                         json={"score_min": 0.55, "release": "v9.9.9", "hold": True})
    assert r.status_code == 200
    assert r.json()["release"] == "v2.2.1" and r.json()["hold"] is False
    assert r.json()["config"]["score_min"] == 0.55


def test_fleet_default_assigned_at_creation(admin_client):
    r = admin_client.get("/api/admin/releases")
    assert r.status_code == 200 and r.json()["fleet_default"] is None
    assert isinstance(r.json()["tags"], list)
    assert admin_client.put("/api/admin/releases/default",
                            json={"release": "not a tag!"}).status_code == 400
    r = admin_client.put("/api/admin/releases/default", json={"release": "v2.2.0"})
    assert r.json()["fleet_default"] == "v2.2.0"
    r = admin_client.post("/api/admin/devices",
                          json={"device_id": "Rpi_fresh", "site_id": "matanzas"})
    assert r.status_code == 201
    assert r.json()["assigned_release"] == "v2.2.0" and r.json()["hold"] is False
    # and the fresh unit can fetch its signed document right away
    from fastapi.testclient import TestClient as _TC
    from app.main import app as _app
    auth_key, config_key = derive_keys(r.json()["key"])
    doc = _TC(_app).get("/api/devices/config",
                        headers={"X-Device-Id": "Rpi_fresh", "X-Device-Key": auth_key}).json()
    from app.services.deviceconfig import sign
    assert doc["config"]["release"] == "v2.2.0" and doc["signature"] == sign(doc, config_key)
    admin_client.delete(f"/api/admin/devices/{r.json()['id']}")
    admin_client.put("/api/admin/releases/default", json={"release": None})


# ── site registry (R-3.1) ────────────────────────────────────────────────────
# These run after the device tests on purpose: once the table has rows it wins
# outright, so the storage fallback can only be observed before the first row.

def test_sites_fall_back_to_storage_until_managed(admin_client):
    """A fixture tree works with no setup: the blob is the fallback."""
    body = admin_client.get("/api/admin/sites").json()
    assert body["source"] == "storage"
    assert sorted(s["id"] for s in body["sites"]) == ["matanzas", "zapallar"]


def test_site_can_be_created_and_then_the_database_wins(admin_client):
    r = admin_client.post("/api/admin/sites", json={
        "id": "lagunillas", "name": "Lagunillas", "lat": -33.98, "lon": -71.86})
    assert r.status_code == 201
    assert r.json()["id"] == "lagunillas"

    body = admin_client.get("/api/admin/sites").json()
    # one row in the table, so the table is authoritative and the blob is ignored
    assert body["source"] == "database"
    assert [s["id"] for s in body["sites"]] == ["lagunillas"]

    # and the user-facing route agrees, because both read one registry
    assert [s["id"] for s in admin_client.get("/api/sites").json()["sites"]] == ["lagunillas"]


def test_import_seeds_the_table_from_storage(admin_client):
    r = admin_client.post("/api/admin/sites/import")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "database"
    assert sorted(s["id"] for s in body["sites"]) == ["lagunillas", "matanzas", "zapallar"]
    # importing twice must not duplicate
    again = admin_client.post("/api/admin/sites/import").json()
    assert len(again["sites"]) == 3


def test_site_id_validated_and_unique(admin_client):
    assert admin_client.post("/api/admin/sites",
                             json={"id": "Bad Site", "name": "x"}).status_code == 400
    assert admin_client.post("/api/admin/sites",
                             json={"id": "zapallar", "name": "dup"}).status_code == 409


def test_registering_a_device_requires_a_known_site(admin_client):
    """The blocker this table exists for: an unknown site must not mint a
    credential, and a fresh container must still be able to get to a known one."""
    r = admin_client.post("/api/admin/devices",
                          json={"device_id": "Rpi_nowhere", "site_id": "atlantis"})
    assert r.status_code == 400
    assert "atlantis" in r.json()["detail"]
    assert admin_client.post("/api/admin/devices",
                             json={"device_id": "Rpi_lagunillas",
                                   "site_id": "lagunillas"}).status_code == 201


def test_site_delete_refuses_while_referenced(admin_client):
    r = admin_client.delete("/api/admin/sites/lagunillas")
    assert r.status_code == 409
    assert "Rpi_lagunillas" in r.json()["detail"]


def test_site_routes_closed_to_operator(client):
    client.post("/api/auth/login", json={"email": "op@x.io", "password": "correct-horse-battery"})
    assert client.get("/api/admin/sites").status_code == 403
    assert client.post("/api/admin/sites", json={"id": "x1", "name": "x"}).status_code == 403
    assert client.delete("/api/admin/sites/zapallar").status_code == 403
    client.post("/api/auth/logout")


def test_config_routes_closed_to_operator(client, cfg_device):
    client.post("/api/auth/login", json={"email": "op@x.io", "password": "correct-horse-battery"})
    assert client.get(f"/api/admin/devices/{cfg_device['pk']}/config").status_code == 403
    assert client.put(f"/api/admin/devices/{cfg_device['pk']}/config",
                      json={"score_min": 0.1}).status_code == 403
    client.post("/api/auth/logout")
