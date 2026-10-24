"""The backend is the only sender (Rpi-Detector D-020).

Twilio is stubbed at `alerts._twilio_post`; what is asserted is *which* alerts
fire, for *which* transition, with *which* template — the logic that used to
live on the device and now lives here.
"""
import os, tempfile

# Settings are a process-wide singleton, so when the whole suite runs in one
# process the first module's environment wins. Everything here therefore
# registers its site in the DB and sets the Twilio settings on the singleton
# directly, instead of relying on the environment.
for _k, _v in {
    "OCEANKIND_SESSION_SECRET": "x" * 40,
    "OCEANKIND_STORAGE_BACKEND": "local",
    "OCEANKIND_LOCAL_STORAGE_ROOT": tempfile.mkdtemp(),
    "OCEANKIND_DB_URL": f"sqlite:///{tempfile.mktemp()}",
    "OCEANKIND_COOKIE_SECURE": "false",
}.items():
    os.environ.setdefault(_k, _v)

import json
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, select
from app.main import app
from app.core.config import settings
from app.core.database import init_db, engine
from app.core.models import User, Site, DeviceAlert
from app.core.security import hash_password, derive_keys
from app.services import alerts

TWILIO = dict(
    twilio_sid="ACtest", twilio_token="tok", twilio_from="whatsapp:+10000000000",
    alert_to="whatsapp:+56900000001, whatsapp:+56900000002", tech_to="whatsapp:+56900000009",
    call_from="+10000000000", call_to="+56900000009", call_cluster_count=3,
    battery_debounce_heartbeats=2, dashboard_url="https://panel.example", alerts_enabled=True,
)

SENT: list[tuple[str, dict]] = []


@pytest.fixture(autouse=True)
def _stub_twilio(monkeypatch):
    alerts.drain()          # leftovers queued by other modules (log-only there)
    SENT.clear()
    s = settings()
    for k, v in TWILIO.items():
        monkeypatch.setattr(s, k, v)
    monkeypatch.setattr(alerts, "_twilio_post", lambda path, form: SENT.append((path, dict(form))))
    yield


@pytest.fixture(scope="module")
def admin():
    init_db()
    SQLModel.metadata.create_all(engine())
    with Session(engine()) as db:
        if not db.exec(select(User).where(User.email == "al@x.io")).first():
            db.add(User(email="al@x.io", password_hash=hash_password("correct-horse-battery"),
                        role="admin"))
        if not db.get(Site, "lagunillas"):
            db.add(Site(site_id="lagunillas", name="Lagunillas"))
        db.commit()
    c = TestClient(app)
    c.post("/api/auth/login", json={"email": "al@x.io", "password": "correct-horse-battery"})
    return c


@pytest.fixture(scope="module")
def creds(admin):
    r = admin.post("/api/admin/devices", json={"device_id": "Rpi_al", "site_id": "lagunillas"})
    assert r.status_code == 201
    return {"X-Device-Id": "Rpi_al", "X-Device-Key": derive_keys(r.json()["key"])[0]}


def _event(n: int, suppressed=False, uploaded=True) -> dict:
    return {
        "schema_version": 2, "site": "lagunillas", "device": "Rpi_al",
        "event_id": f"00000000-0000-4000-8000-0000000000{n:02d}",
        "captured_utc": f"2026-10-24T12:00:{n:02d}+00:00", "event_type": "vessel",
        "score": 0.91, "audio_level": 0.1234, "suppressed": suppressed,
        "clip": {"path": f"sites/lagunillas/events/2026/10/24/clip{n}.wav", "uploaded": uploaded},
    }


def _hb(n: int, degraded=None, voltage=12.6) -> dict:
    return {
        "schema_version": 2, "site": "lagunillas", "device": "Rpi_al",
        "generated_utc": f"2026-10-24T12:{n:02d}:00+00:00",
        "last_seen": f"2026-10-24T12:{n:02d}:00+00:00",
        "health": {"detector_ok": True, "audio_ok": True, "degraded_reason": degraded},
        "power": {"battery_voltage_v": voltage, "panel_power_w": 0.0},
    }


def test_transport_is_twilio_when_configured(admin):
    assert alerts.transport() == "twilio"
    assert admin.get("/api/health").json()["alerts"] == "twilio"


def test_detection_push_sends_one_message_per_recipient_with_play_link(admin, creds):
    r = admin.post("/api/devices/events", headers=creds, json=_event(1))
    assert r.status_code == 202 and r.json()["indexed"] is True
    assert alerts.drain() == 1
    assert [p for p, _ in SENT] == ["Messages", "Messages"]
    form = SENT[0][1]
    assert form["ContentSid"] == alerts.settings().wa_tpl_alert
    assert form["To"] == "whatsapp:+56900000001"
    vars_ = json.loads(form["ContentVariables"])
    assert vars_["1"] == "Lagunillas"                # station from the registry
    assert vars_["2"] == "EMBARCACIÓN"
    assert vars_["5"] == "91.0%"
    assert vars_["6"].startswith("https://panel.example/?play=sites%2Flagunillas")


def test_replay_announces_nothing(admin, creds):
    r = admin.post("/api/devices/events", headers=creds, json=_event(1))
    assert r.status_code == 202 and r.json()["indexed"] is False
    assert alerts.drain() == 0 and SENT == []


def test_suppressed_is_recorded_not_announced_but_counts_for_cluster(admin, creds):
    admin.post("/api/devices/events", headers=creds, json=_event(2, suppressed=True))
    assert alerts.drain() == 0 and SENT == []
    # third event at the site inside the window → voice call, plus its own message
    admin.post("/api/devices/events", headers=creds, json=_event(3))
    alerts.drain()
    paths = [p for p, _ in SENT]
    assert paths.count("Calls") == 1 and paths.count("Messages") == 2
    call = next(f for p, f in SENT if p == "Calls")
    assert call["To"] == "+56900000009" and "Lagunillas" in call["Twiml"]
    # cooldown: a fourth does not call again
    SENT.clear()
    admin.post("/api/devices/events", headers=creds, json=_event(4))
    alerts.drain()
    assert [p for p, _ in SENT] == ["Messages", "Messages"]


def test_degraded_transition_opens_notifies_and_clears(admin, creds):
    assert admin.post("/api/devices/heartbeat", headers=creds, json=_hb(1)).status_code == 202
    assert alerts.drain() == 0
    admin.post("/api/devices/heartbeat", headers=creds, json=_hb(2, degraded="audio stalled"))
    assert alerts.drain() == 1
    assert SENT[0][1]["To"] == "whatsapp:+56900000009"        # TECH_TO, not ALERT_TO
    assert "audio stalled" in SENT[0][1]["ContentVariables"]
    with Session(engine()) as db:
        row = db.exec(select(DeviceAlert).where(DeviceAlert.kind == "degraded")).one()
        assert row.cleared_utc is None and row.notify_count == 1
        assert row.detail == "audio stalled"
    # same reason again: nothing new
    SENT.clear()
    admin.post("/api/devices/heartbeat", headers=creds, json=_hb(3, degraded="audio stalled"))
    assert alerts.drain() == 0
    # recovery
    admin.post("/api/devices/heartbeat", headers=creds, json=_hb(4))
    assert alerts.drain() == 1 and "RECUPERADO" in SENT[0][1]["ContentVariables"]
    with Session(engine()) as db:
        row = db.exec(select(DeviceAlert).where(DeviceAlert.kind == "degraded")).one()
        assert row.cleared_utc is not None
    admin_alerts = admin.get("/api/admin/alerts?open_only=false").json()
    ours = [a for a in admin_alerts if a["kind"] == "degraded" and a["site_id"] == "lagunillas"]
    assert ours and ours[0]["detail"] == "audio stalled" and ours[0]["open"] is False


def test_battery_is_debounced_and_escalates_once_per_level(admin, creds):
    admin.post("/api/devices/heartbeat", headers=creds, json=_hb(10, voltage=11.5))
    assert alerts.drain() == 0                          # one reading is not an alert
    admin.post("/api/devices/heartbeat", headers=creds, json=_hb(11, voltage=11.5))
    assert alerts.drain() == 1
    form = SENT[0][1]
    assert form["ContentSid"] == alerts.settings().wa_tpl_battery
    assert json.loads(form["ContentVariables"])["3"] == "BAJA"
    SENT.clear()
    # still low: silent. drops to critical: one more, once.
    admin.post("/api/devices/heartbeat", headers=creds, json=_hb(12, voltage=11.6))
    admin.post("/api/devices/heartbeat", headers=creds, json=_hb(13, voltage=11.0))
    admin.post("/api/devices/heartbeat", headers=creds, json=_hb(14, voltage=11.0))
    assert alerts.drain() == 1 and json.loads(SENT[0][1]["ContentVariables"])["3"] == "CRITICA"
    SENT.clear()
    admin.post("/api/devices/heartbeat", headers=creds, json=_hb(15, voltage=12.4))
    admin.post("/api/devices/heartbeat", headers=creds, json=_hb(16, voltage=12.4))
    assert alerts.drain() == 1 and "recuperada" in SENT[0][1]["ContentVariables"]


def test_heartbeat_message_uses_latest_status(admin, creds):
    from app.services import scheduler
    # ≥1: in the full suite other modules' sites may also have a status row
    assert scheduler.send_heartbeat_messages() >= 1
    assert alerts.drain() >= 1
    ours = [f for p, f in SENT if "Lagunillas" in f["ContentVariables"]]
    assert len(ours) == 1
    assert ours[0]["ContentSid"] == alerts.settings().wa_tpl_heartbeat
    assert "grabando OK" in ours[0]["ContentVariables"]


def test_log_only_when_unconfigured(monkeypatch):
    s = alerts.settings()
    monkeypatch.setattr(s, "twilio_token", "")
    assert alerts.transport() == "log-only"
    assert alerts.send_whatsapp("HX1", {"1": "x"}, ["whatsapp:+1"]) is None
    assert SENT == []
