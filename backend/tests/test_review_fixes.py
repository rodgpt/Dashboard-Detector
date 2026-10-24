"""Fixes from the 2026-10-24 repository health review (FABLE_REPORT.md, Batch B).

Each test names the defect it pins down. The common thread: every one of these
was a path where the system could be wrong while looking fine — an index that
lost history and reported zero drift, a dead device that could never be flagged,
a credential readable through a URL, alerts recorded and shown to nobody.
"""
import os, tempfile, json, pathlib

for _k, _v in {
    "OCEANKIND_SESSION_SECRET": "x" * 40,
    "OCEANKIND_STORAGE_BACKEND": "local",
    "OCEANKIND_LOCAL_STORAGE_ROOT": tempfile.mkdtemp(),
    "OCEANKIND_DB_URL": f"sqlite:///{tempfile.mktemp()}",
    "OCEANKIND_COOKIE_SECURE": "false",
    "OCEANKIND_CONFIG_HMAC_KEY": "test-signing-key-0123456789abcdef",
    "OCEANKIND_RECONCILE_INTERVAL_HOURS": "0",
}.items():
    os.environ.setdefault(_k, _v)

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, select

from app.main import app
from app.core import rate_limit
from app.core.config import Settings, settings
from app.core.database import init_db, engine
from app.core.models import (DetectionEvent, Device, DeviceAlert, DeviceStatus,
                             DeviceStatusHistory, IndexerRun, Site, User)
from app.core.security import hash_password
from app.services import silence
from app.services.storage import LocalStorage, get_storage

SITE = "revw"
DEVICE = "Rpi_revw"
NOW = datetime.now(timezone.utc)

root = pathlib.Path(os.environ["OCEANKIND_LOCAL_STORAGE_ROOT"])
root.mkdir(parents=True, exist_ok=True)


def blob(captured: datetime, event_id: str) -> None:
    doc = {
        "schema_version": 2, "site": SITE, "device": DEVICE,
        "event_id": event_id, "captured_utc": captured.isoformat(),
        "event_type": "vessel", "detector": "psd_tonal", "score": 0.7,
        "suppressed": False,
    }
    path = (root / f"sites/{SITE}/events/{captured:%Y/%m/%d}/"
                   f"{captured:%Y-%m-%dT%H-%M-%S}_{event_id}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))


@pytest.fixture(scope="module")
def admin():
    init_db()
    SQLModel.metadata.create_all(engine())
    with Session(engine()) as db:
        if not db.exec(select(User).where(User.email == "rv@x.io")).first():
            db.add(User(email="rv@x.io",
                        password_hash=hash_password("correct-horse-battery"), role="admin"))
        if not db.get(Site, SITE):
            db.add(Site(site_id=SITE, name="Review"))
        db.commit()
    c = TestClient(app)
    c.post("/api/auth/login", json={"email": "rv@x.io", "password": "correct-horse-battery"})
    return c


@pytest.fixture(scope="module")
def creds(admin):
    r = admin.post("/api/admin/devices", json={"device_id": DEVICE, "site_id": SITE})
    assert r.status_code == 201
    from app.core.security import derive_keys
    return {"X-Device-Id": DEVICE, "X-Device-Key": derive_keys(r.json()["key"])[0],
            "pk": r.json()["id"]}


def headers(creds):
    return {k: v for k, v in creds.items() if k != "pk"}


@pytest.fixture(autouse=True)
def clean():
    with Session(engine()) as s:
        for row in s.exec(select(DetectionEvent).where(DetectionEvent.site_id == SITE)).all():
            s.delete(row)
        for row in s.exec(select(IndexerRun).where(IndexerRun.site_id == SITE)).all():
            s.delete(row)
        for row in s.exec(select(DeviceAlert).where(DeviceAlert.site_id == SITE)).all():
            s.delete(row)
        d = s.exec(select(Device).where(Device.device_id == DEVICE)).first()
        if d:
            for row in s.exec(select(DeviceStatus).where(DeviceStatus.device_id == d.id)).all():
                s.delete(row)
            for row in s.exec(select(DeviceStatusHistory)
                              .where(DeviceStatusHistory.device_id == d.id)).all():
                s.delete(row)
            d.last_push_error = None; d.last_push_error_utc = None; d.last_push_utc = None
            s.add(d)
        s.commit()
    for p in (root / f"sites/{SITE}").rglob("*"):
        if p.is_file():
            p.unlink()
    yield


# ── BE-01 / BE-03: the index rebuild and the window ───────────────────────────

def test_rebuild_covers_the_whole_history_not_the_trailing_window(admin):
    """Drop everything, rebuild, and an event 30 days old must come back. Before
    2026-10-24 the pass after the drop covered 14 days, and drift read zero
    because drift is measured over the same window."""
    blob(NOW - timedelta(days=30), "old0-0000-4000-8000-000000000001")
    blob(NOW, "new0-0000-4000-8000-000000000002")

    r = admin.post("/api/admin/index/reconcile", params={"site_id": SITE})
    assert r.json()[0]["newly_indexed"] == 1, "the scheduled window is 14 days; only the new one"

    r = admin.post("/api/admin/index/rebuild", json={"site_id": SITE, "confirm_site_id": SITE})
    assert r.status_code == 200
    assert r.json()["newly_indexed"] == 2, r.json()
    page = admin.get(f"/api/sites/{SITE}/events",
                     params={"limit": 50, "since": (NOW - timedelta(days=60)).isoformat()}).json()
    assert page["total"] == 2
    with Session(engine()) as db:
        run = db.exec(select(IndexerRun).where(IndexerRun.site_id == SITE)
                      .order_by(IndexerRun.id.desc())).first()   # type: ignore[attr-defined]
        assert run.trigger == "rebuild" and run.window_days >= 31


def test_manual_reconcile_honours_the_configured_window(admin, monkeypatch):
    monkeypatch.setattr(settings(), "reconcile_window_days", 45)
    blob(NOW - timedelta(days=30), "win0-0000-4000-8000-000000000003")
    r = admin.post("/api/admin/index/reconcile", params={"site_id": SITE})
    assert r.json()[0]["newly_indexed"] == 1
    with Session(engine()) as db:
        run = db.exec(select(IndexerRun).where(IndexerRun.site_id == SITE)).first()
        assert run.window_days == 45


# ── BE-02: the device clock is not the liveness clock ─────────────────────────

def _status(last_seen: datetime) -> dict:
    return {"schema_version": 2, "site": SITE, "device": DEVICE,
            "generated_utc": last_seen.isoformat(), "last_seen": last_seen.isoformat(),
            "health": {"detector_ok": True, "audio_ok": True, "duty_cycle_pct": 99.0}}


def test_heartbeat_far_in_the_future_is_rejected(admin, creds):
    r = admin.post("/api/devices/heartbeat", headers=headers(creds),
                   json=_status(NOW + timedelta(days=1)))
    assert r.status_code == 400 and "future" in r.json()["detail"]
    with Session(engine()) as db:
        assert db.get(DeviceStatus, creds["pk"]) is None, "a wrong clock must not poison the row"


def test_heartbeat_with_small_skew_is_accepted(admin, creds):
    r = admin.post("/api/devices/heartbeat", headers=headers(creds),
                   json=_status(NOW + timedelta(seconds=60)))
    assert r.status_code == 202 and r.json()["accepted"] is True


def test_admin_can_reset_a_poisoned_status_row(admin, creds):
    admin.post("/api/devices/heartbeat", headers=headers(creds),
               json=_status(NOW + timedelta(seconds=200)))
    # A correct heartbeat is now "stale" against the skewed one...
    r = admin.post("/api/devices/heartbeat", headers=headers(creds), json=_status(NOW))
    assert r.json()["accepted"] is False
    # ...until the row is reset. History is kept.
    assert admin.delete(f"/api/admin/devices/{creds['pk']}/status").status_code == 204
    r = admin.post("/api/devices/heartbeat", headers=headers(creds), json=_status(NOW))
    assert r.json()["accepted"] is True
    with Session(engine()) as db:
        hist = db.exec(select(DeviceStatusHistory)
                       .where(DeviceStatusHistory.device_id == creds["pk"])).all()
        assert len(hist) == 2


def test_silence_check_uses_when_we_received_the_heartbeat(admin, creds, monkeypatch, tmp_path):
    """A device whose clock is a year ahead reported once and then died. With the
    device's own timestamp `quiet_for` was negative forever and no alert could
    fire. Silence is measured from the server's receive time."""
    sent: list[str] = []
    monkeypatch.setattr(silence, "_notify", lambda alert, msg: (sent.append(msg), None)[1])
    with Session(engine()) as db:
        db.add(DeviceStatus(device_id=creds["pk"],
                            reported_last_seen=NOW + timedelta(days=365),
                            received_utc=NOW - timedelta(hours=3),
                            payload=_status(NOW + timedelta(days=365))))
        db.commit()
        r = silence.check_site(db, LocalStorage(str(tmp_path)), SITE, now=NOW)
    assert r.outcome == silence.OPENED, r
    assert len(sent) == 1


def test_blob_last_seen_in_the_future_is_clamped_to_now(monkeypatch, tmp_path):
    sent: list[str] = []
    monkeypatch.setattr(silence, "_notify", lambda alert, msg: (sent.append(msg), None)[1])
    storage = LocalStorage(str(tmp_path))
    storage.put(f"sites/{SITE}/status.json", json.dumps(
        _status(NOW + timedelta(hours=1))).encode())
    with Session(engine()) as db:
        assert silence.check_site(db, storage, SITE, now=NOW).outcome == silence.OK
        # Real time catches up with and passes the bogus timestamp: 3 h quiet.
        later = NOW + timedelta(hours=4)
        assert silence.check_site(db, storage, SITE, now=later).outcome == silence.OPENED


# ── BE-04: the clip route cannot leave the storage tree ───────────────────────

def test_local_storage_refuses_to_escape_its_root(tmp_path):
    s = LocalStorage(str(tmp_path / "root"))
    (tmp_path / "root").mkdir()
    (tmp_path / "secret.txt").write_text("nope")
    assert s.exists("../secret.txt") is False
    with pytest.raises(PermissionError):
        s.get("../secret.txt")
    assert s.list("../") == []


def test_clip_route_rejects_traversal_and_serves_real_clips(admin):
    r = admin.get(f"/api/sites/{SITE}/clips/..%2F..%2F..%2Fetc%2Fpasswd")
    assert r.status_code == 400
    r = admin.get(f"/api/sites/{SITE}/clips/2026/10/24/%2E%2E/x.wav")
    assert r.status_code == 400
    r = admin.get(f"/api/sites/{SITE}/clips/2026/10/24/missing.wav")
    assert r.status_code == 404

    clip = root / f"sites/{SITE}/clips/2026/10/24/abc.wav"
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(b"RIFF....WAVEfmt ")
    r = admin.get(f"/api/sites/{SITE}/clips/2026/10/24/abc.wav")
    assert r.status_code == 200 and r.headers["content-type"].startswith("audio/wav")


# ── BE-05: what was recorded is now shown ────────────────────────────────────

def test_devices_list_exposes_push_health(admin, creds):
    bad = {"schema_version": 2, "site": "other-site", "event_id": "x"}
    r = admin.post("/api/devices/events", headers=headers(creds), json=bad)
    assert r.status_code == 403
    me = next(d for d in admin.get("/api/admin/devices").json() if d["device_id"] == DEVICE)
    assert me["last_push_error_utc"] is not None
    assert "site mismatch" in me["last_push_error"]
    assert me["last_push_utc"] is None


def test_alert_routes_show_open_outages(admin):
    with Session(engine()) as db:
        db.add(DeviceAlert(site_id=SITE, kind="silent", opened_utc=NOW - timedelta(hours=2),
                           last_seen_utc=NOW - timedelta(hours=5)))
        db.add(DeviceAlert(site_id=SITE, kind="silent", opened_utc=NOW - timedelta(days=3),
                           last_seen_utc=NOW - timedelta(days=3), cleared_utc=NOW - timedelta(days=2)))
        db.commit()
    open_ = admin.get("/api/admin/alerts").json()
    assert [a["site_id"] for a in open_ if a["site_id"] == SITE] == [SITE]
    assert all(a["open"] for a in open_)
    everything = admin.get("/api/admin/alerts", params={"open_only": "false"}).json()
    assert len([a for a in everything if a["site_id"] == SITE]) == 2

    site = admin.get(f"/api/sites/{SITE}/alerts").json()
    assert len(site["alerts"]) == 1 and site["alerts"][0]["open"] is True

    # Site-scoped like every other site route: an operator without the site gets 403.
    with Session(engine()) as db:
        if not db.exec(select(User).where(User.email == "rvop@x.io")).first():
            db.add(User(email="rvop@x.io", password_hash=hash_password("correct-horse-battery"),
                        role="operator"))
            db.commit()
    op = TestClient(app)
    op.post("/api/auth/login", json={"email": "rvop@x.io", "password": "correct-horse-battery"})
    assert op.get(f"/api/sites/{SITE}/alerts").status_code == 403
    assert op.get("/api/admin/alerts").status_code == 403


def test_health_says_whether_anyone_is_notified(admin):
    body = admin.get("/api/health").json()
    assert body["alerts"] in ("twilio", "log-only", "off")


# ── FE-03 backing routes: event by id, hourly buckets ─────────────────────────

def test_event_by_id_and_hourly_summary(admin):
    old = NOW - timedelta(hours=50)
    blob(old, "hrly-0000-4000-8000-000000000011")
    blob(NOW - timedelta(minutes=5), "hrly-0000-4000-8000-000000000012")
    admin.post("/api/admin/index/reconcile", params={"site_id": SITE})

    r = admin.get(f"/api/sites/{SITE}/events/hrly-0000-4000-8000-000000000011")
    assert r.status_code == 200 and r.json()["event_id"] == "hrly-0000-4000-8000-000000000011"
    assert admin.get(f"/api/sites/{SITE}/events/nope-0000-4000-8000-000000000000").status_code == 404
    # The literal `summary` still routes to the summary, not to a lookup.
    assert "by_day" in admin.get(f"/api/sites/{SITE}/events/summary").json()

    since = (NOW - timedelta(hours=72)).isoformat()
    plain = admin.get(f"/api/sites/{SITE}/events/summary", params={"since": since}).json()
    assert plain["hourly"] == [] and plain["total"] == 2
    full = admin.get(f"/api/sites/{SITE}/events/summary",
                     params={"since": since, "hourly": "true"}).json()
    assert 72 <= len(full["hourly"]) <= 74            # one bucket per clock hour, zero-filled
    assert sum(b["count"] for b in full["hourly"]) == 2
    assert all(set(b) == {"ts", "count"} for b in full["hourly"])


# ── BE-07: boot-time refusals and the throttle ──────────────────────────────────

def test_unimplemented_storage_backend_refuses_to_start():
    with pytest.raises(RuntimeError):
        Settings(session_secret="x" * 40, storage_backend="s3", s3_bucket="b").validate_runtime()


def test_login_throttle_does_not_keep_empty_keys():
    rate_limit._FAILS.clear()
    rate_limit.record_failure("1.2.3.4:a@x.io")
    rate_limit._FAILS["1.2.3.4:a@x.io"] = [0.0]      # a failure long outside the window
    assert rate_limit.too_many("1.2.3.4:a@x.io") is False
    assert "1.2.3.4:a@x.io" not in rate_limit._FAILS
    assert rate_limit.too_many("never-seen") is False
    assert "never-seen" not in rate_limit._FAILS
