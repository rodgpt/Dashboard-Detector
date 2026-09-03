"""Device-silence alerting, and above all: not flooding anyone (R-7.5, D-022).

The check runs every few minutes and the notification must not. Most of these
tests are about the difference — an alerting system that cries every five minutes
teaches people to ignore it, which leaves the unit just as unattended as no
alerting at all.
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
from sqlmodel import Session, SQLModel, select

from app.core.config import settings
from app.core.database import engine
from app.core.models import Device, DeviceAlert, DeviceConfig
from app.services import silence
from app.services.silence import (
    OK, OPENED, RECOVERED, RENOTIFIED, STILL_SILENT, UNKNOWN,
    check_site, threshold_seconds,
)
from app.services.storage import LocalStorage

SITE = "matanzas"
NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def storage(tmp_path):
    return LocalStorage(str(tmp_path))


@pytest.fixture()
def db():
    SQLModel.metadata.create_all(engine())
    with Session(engine()) as s:
        for row in s.exec(select(DeviceAlert)).all():
            s.delete(row)
        for row in s.exec(select(DeviceConfig)).all():
            s.delete(row)
        for row in s.exec(select(Device)).all():
            s.delete(row)
        s.commit()
        yield s


@pytest.fixture(autouse=True)
def sent(monkeypatch):
    """Capture notifications instead of sending them."""
    out: list[str] = []
    monkeypatch.setattr(silence, "_notify", lambda alert, msg: (out.append(msg), None)[1])
    return out


def status(storage: LocalStorage, last_seen: datetime) -> None:
    storage.put(f"sites/{SITE}/status.json", json.dumps({
        "schema_version": 2, "site": SITE, "device": "Rpi_matanzas",
        "last_seen": last_seen.isoformat(),
        "generated_utc": last_seen.isoformat(),
    }).encode())


def open_alerts(db) -> list[DeviceAlert]:
    return [a for a in db.exec(select(DeviceAlert)).all() if a.open]


# --- the basic transition ----------------------------------------------------

def test_a_reporting_device_raises_nothing(db, storage, sent):
    status(storage, NOW - timedelta(minutes=1))
    assert check_site(db, storage, SITE, now=NOW).outcome == OK
    assert sent == [] and open_alerts(db) == []


def test_a_silent_device_opens_an_alert_and_notifies_once(db, storage, sent):
    status(storage, NOW - timedelta(hours=3))
    r = check_site(db, storage, SITE, now=NOW)
    assert r.outcome == OPENED
    assert len(sent) == 1 and "sin señal" in sent[0]
    assert len(open_alerts(db)) == 1


def test_recovery_closes_the_alert_and_says_so(db, storage, sent):
    status(storage, NOW - timedelta(hours=3))
    check_site(db, storage, SITE, now=NOW)
    status(storage, NOW + timedelta(minutes=1))          # it reported again
    r = check_site(db, storage, SITE, now=NOW + timedelta(minutes=2))
    assert r.outcome == RECOVERED
    assert open_alerts(db) == []
    assert "volvió a reportar" in sent[-1]


# --- not flooding anyone. the point of the whole design. --------------------

def test_repeated_checks_while_silent_notify_once(db, storage, sent):
    """The check runs every five minutes. A unit down all night must not produce
    a message every five minutes, or people stop reading them."""
    status(storage, NOW - timedelta(hours=3))
    outcomes = [check_site(db, storage, SITE,
                           now=NOW + timedelta(minutes=5 * i)).outcome
                for i in range(12)]           # an hour of checking
    assert outcomes[0] == OPENED
    assert set(outcomes[1:]) == {STILL_SILENT}
    assert len(sent) == 1, f"flooded: {len(sent)} notifications for one outage"
    assert len(open_alerts(db)) == 1, "opened more than one alert for one outage"


def test_it_repeats_only_after_the_renotify_period(db, storage, sent):
    status(storage, NOW - timedelta(hours=3))
    check_site(db, storage, SITE, now=NOW)
    assert len(sent) == 1

    # 23 h later: still quiet, still nothing said
    check_site(db, storage, SITE, now=NOW + timedelta(hours=23))
    assert len(sent) == 1

    # past the 24 h default: one reminder, not a stream
    r = check_site(db, storage, SITE, now=NOW + timedelta(hours=25))
    assert r.outcome == RENOTIFIED
    assert len(sent) == 2
    check_site(db, storage, SITE, now=NOW + timedelta(hours=25, minutes=5))
    assert len(sent) == 2


def test_renotify_zero_means_exactly_one_message_per_outage(db, storage, sent, monkeypatch):
    monkeypatch.setattr(settings(), "silence_renotify_hours", 0.0)
    status(storage, NOW - timedelta(hours=3))
    check_site(db, storage, SITE, now=NOW)
    for days in range(1, 8):
        check_site(db, storage, SITE, now=NOW + timedelta(days=days))
    assert len(sent) == 1


def test_a_second_outage_notifies_again(db, storage, sent):
    """Quiet about an *ongoing* outage, not about a new one."""
    status(storage, NOW - timedelta(hours=3))
    check_site(db, storage, SITE, now=NOW)
    status(storage, NOW + timedelta(minutes=1))
    check_site(db, storage, SITE, now=NOW + timedelta(minutes=2))    # recovered
    status(storage, NOW + timedelta(minutes=2))
    r = check_site(db, storage, SITE, now=NOW + timedelta(hours=6))  # down again
    assert r.outcome == OPENED
    # "sin señal desde hace" is the outage wording. Matching bare "sin señal"
    # also catches the recovery message ("estuvo sin señal 2 min"), which is a
    # third message but not a third outage.
    assert len([m for m in sent if "sin señal desde hace" in m]) == 2
    assert len([m for m in sent if "volvió a reportar" in m]) == 1


# --- the threshold, and why it is in heartbeats ------------------------------

def test_threshold_follows_the_tuned_heartbeat(db, storage):
    """`heartbeat_interval_s` is remotely tunable 30–3600 s, so a fixed duration
    would mean 120 missed beats on one setting and less than one on another."""
    base = threshold_seconds(db, SITE)
    db.add(Device(device_id="Rpi_matanzas", site_id=SITE, key_hash="x"))
    db.commit()
    db.add(DeviceConfig(device_id="Rpi_matanzas",
                        config_json=json.dumps({"heartbeat_interval_s": 600.0})))
    db.commit()
    slow = threshold_seconds(db, SITE)
    assert slow > base
    assert slow == 600.0 * settings().silence_after_missed_heartbeats


def test_a_fast_heartbeat_cannot_make_it_twitchy(db, storage):
    """The floor. Without it a 30 s heartbeat would warn after 10 minutes."""
    db.add(Device(device_id="Rpi_matanzas", site_id=SITE, key_hash="x"))
    db.commit()
    db.add(DeviceConfig(device_id="Rpi_matanzas",
                        config_json=json.dumps({"heartbeat_interval_s": 30.0})))
    db.commit()
    assert threshold_seconds(db, SITE) >= settings().silence_min_minutes * 60


def test_a_device_quiet_but_within_threshold_is_not_alerted(db, storage, sent):
    status(storage, NOW - timedelta(minutes=10))       # under the 15 min floor
    assert check_site(db, storage, SITE, now=NOW).outcome == OK
    assert sent == []


# --- "we cannot tell" is not "it is dead" ------------------------------------

def test_a_missing_status_blob_is_unknown_not_silence(db, storage, sent):
    """Announcing a dead device when we actually mean "we could not read the
    blob" is how an alerting system trains people to ignore it."""
    r = check_site(db, storage, SITE, now=NOW)
    assert r.outcome == UNKNOWN
    assert sent == [] and open_alerts(db) == []


def test_a_malformed_status_blob_is_unknown_not_silence(db, storage, sent):
    storage.put(f"sites/{SITE}/status.json", b"{not json")
    assert check_site(db, storage, SITE, now=NOW).outcome == UNKNOWN
    assert sent == []


def test_generated_utc_is_used_when_last_seen_is_absent(db, storage, sent):
    storage.put(f"sites/{SITE}/status.json", json.dumps({
        "schema_version": 2, "site": SITE,
        "generated_utc": (NOW - timedelta(minutes=2)).isoformat(),
    }).encode())
    assert check_site(db, storage, SITE, now=NOW).outcome == OK


# --- an alert that was never delivered must be visible -----------------------

def test_a_failed_notification_is_recorded_on_the_alert(db, storage, monkeypatch):
    """An alert raised and never delivered is the silent failure this module
    exists to prevent, so the failure lands on the row."""
    monkeypatch.setattr(silence, "_notify", lambda alert, msg: "SMTPError: refused")
    status(storage, NOW - timedelta(hours=3))
    check_site(db, storage, SITE, now=NOW)
    alert = open_alerts(db)[0]
    assert alert.notified_utc is None
    assert "refused" in alert.notify_error
    assert alert.notify_count == 0
