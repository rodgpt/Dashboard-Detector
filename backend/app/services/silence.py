"""Noticing that a device has stopped reporting, and telling somebody (R-7.5).

R-7.4 puts device health on a screen. That is enough for a unit somebody is
already looking at, and useless for one that dies at 02:00 and is discovered at
09:00. Given the system exists to notice detonations at sea, a silently dead node
is precisely the failure it is supposed to prevent — so silence has to reach a
person without anyone thinking to look.

Liveness comes from `status.json → last_seen`
---------------------------------------------
Not from `Device.last_seen`, which looks like the obvious signal and is not. That
column is stamped when a device *authenticates to our API*, and under D-022 the
device only does that when it has an event to push. A healthy unit in a quiet
week would look dead. The device writes `status.json` every heartbeat regardless,
and `DATA-CONTRACT.md` says outright that liveness is derived from that field —
so that is what this reads.

Not flooding anyone
-------------------
The check runs every few minutes; the notification does not. All four knobs that
govern volume live in `core/config.py` under **device-silence alerting**, and
nothing else in the codebase decides when anyone is told:

- `silence_check_interval_minutes` — how often we look (cheap, one blob per site)
- `silence_after_missed_heartbeats` + `silence_min_minutes` — how long before the
  first warning
- `silence_renotify_hours` — **how often we repeat ourselves.** An open alert
  notifies once, then stays quiet for this long however many checks run in
  between. A unit down for a week sends 7 messages at the default, not 2,016.
  Zero means notify once per outage and never repeat.
- `silence_alerts_enabled` — off entirely

The state that makes it work is one `DeviceAlert` row per outage. Without
somewhere to record "already told them", every pass would notify again, which is
the flood.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlmodel import Session, select

from app.core.config import settings
from app.core.models import DeviceAlert, DeviceConfig, Device, as_utc
from app.services.storage import Storage

log = logging.getLogger(__name__)

STATUS_BLOB = "sites/{site_id}/status.json"

# What we did on one site, for the caller and for tests.
OK = "ok"                    # reporting normally
OPENED = "opened"            # went silent; alert raised and notified
STILL_SILENT = "still"       # already known silent; notification suppressed
RENOTIFIED = "renotified"    # still silent, and the quiet period elapsed
RECOVERED = "recovered"      # came back; alert closed
UNKNOWN = "unknown"          # no status blob, or no usable timestamp


@dataclass
class SilenceCheck:
    site_id: str
    outcome: str
    last_seen: Optional[datetime] = None
    silent_for_s: Optional[float] = None
    threshold_s: Optional[float] = None
    detail: Optional[str] = None


def _heartbeat_s(db: Session, site_id: str) -> float:
    """The heartbeat this site's device is actually running.

    From its tuned configuration when there is one, because a device told to beat
    every 300 s must not be called dead at 20 minutes. Falls back to the
    contract's default.
    """
    s = settings()
    device = db.exec(select(Device).where(Device.site_id == site_id)).first()
    if device:
        row = db.exec(select(DeviceConfig)
                      .where(DeviceConfig.device_id == device.device_id)).first()
        if row:
            try:
                value = json.loads(row.config_json).get("heartbeat_interval_s")
                if isinstance(value, (int, float)) and value > 0:
                    return float(value)
            except Exception:                                   # noqa: BLE001
                pass
    return s.assumed_heartbeat_s


def threshold_seconds(db: Session, site_id: str) -> float:
    """How long a site may be quiet before it counts as silent.

    Missed heartbeats rather than a fixed duration, with a floor. `heartbeat_
    interval_s` is remotely tunable from 30 s to 3600 s, so "one hour" would mean
    120 missed beats on one setting and less than one on another — the floor is
    what stops a fast heartbeat making the whole system twitchy.
    """
    s = settings()
    return max(s.silence_min_minutes * 60.0,
               _heartbeat_s(db, site_id) * s.silence_after_missed_heartbeats)


def _last_seen(storage: Storage, site_id: str) -> Optional[datetime]:
    """`status.json → last_seen`, or `generated_utc` if that is absent.

    Returns None when the blob is missing or unparseable. That is reported as
    `unknown` rather than as silence: "we cannot tell" and "the device is dead"
    are different, and announcing the second when we mean the first is how an
    alerting system trains people to ignore it.
    """
    try:
        doc = json.loads(storage.get(STATUS_BLOB.format(site_id=site_id)))
    except Exception:                                           # noqa: BLE001
        return None
    for field in ("last_seen", "generated_utc"):
        value = doc.get(field)
        if isinstance(value, str) and value:
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError:
                continue
            return as_utc(parsed)
    return None


def _notify(alert: DeviceAlert, message: str) -> Optional[str]:
    """Send one notification. Returns an error string, or None on success.

    A plain webhook, and log-only when none is configured. Portable by
    construction (R-1.1): no cloud notification service, so it works with
    whatever the client already runs. Twilio is the obvious eventual transport
    and stays blocked on client console access (F-04) — the alert is recorded
    regardless, so nothing is lost in the meantime.
    """
    s = settings()
    log.warning("DEVICE ALERT [%s] %s", alert.site_id, message)
    if not s.silence_webhook_url:
        return None
    try:
        import urllib.request
        payload = json.dumps({
            "kind": alert.kind, "site_id": alert.site_id, "message": message,
            "opened_utc": alert.opened_utc.isoformat(),
            "last_seen_utc": alert.last_seen_utc.isoformat() if alert.last_seen_utc else None,
            "notify_count": alert.notify_count + 1,
        }).encode()
        req = urllib.request.Request(
            s.silence_webhook_url, data=payload,
            headers={"content-type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10):
            return None
    except Exception as e:                                      # noqa: BLE001
        # Recorded on the alert, not swallowed: an alert raised and never
        # delivered is the silent failure this whole module exists to prevent.
        log.exception("device alert webhook failed for %s", alert.site_id)
        return f"{type(e).__name__}: {e}"[:300]


def _fmt(seconds: float) -> str:
    h, m = divmod(int(seconds // 60), 60)
    return f"{h} h {m} min" if h else f"{m} min"


def check_site(db: Session, storage: Storage, site_id: str, *,
               now: Optional[datetime] = None) -> SilenceCheck:
    """Evaluate one site and open, hold, repeat or close its alert."""
    s = settings()
    now = now or datetime.now(timezone.utc)

    open_alert = db.exec(
        select(DeviceAlert)
        .where(DeviceAlert.site_id == site_id, DeviceAlert.kind == "silent")
        .where(DeviceAlert.cleared_utc == None)                 # noqa: E711
    ).first()

    last_seen = _last_seen(storage, site_id)
    if last_seen is None:
        # No usable status blob. Not treated as silence — see `_last_seen`.
        return SilenceCheck(site_id, UNKNOWN,
                            detail="no readable status.json for this site")

    threshold = threshold_seconds(db, site_id)
    quiet_for = (now - last_seen).total_seconds()
    silent = quiet_for > threshold

    if not silent:
        if open_alert:
            open_alert.cleared_utc = now
            db.add(open_alert)
            db.commit()
            # as_utc: SQLite hands these back naive. See models.as_utc.
            downtime = (now - as_utc(open_alert.opened_utc)).total_seconds()
            _notify(open_alert,
                    f"{site_id}: el equipo volvió a reportar "
                    f"(estuvo sin señal {_fmt(downtime)}).")
            return SilenceCheck(site_id, RECOVERED, last_seen, quiet_for, threshold)
        return SilenceCheck(site_id, OK, last_seen, quiet_for, threshold)

    message = (f"{site_id}: sin señal desde hace {_fmt(quiet_for)} "
               f"(último reporte {last_seen.isoformat()}).")

    if open_alert is None:
        alert = DeviceAlert(site_id=site_id, kind="silent",
                            opened_utc=now, last_seen_utc=last_seen)
        db.add(alert)
        db.commit()
        db.refresh(alert)
        err = _notify(alert, message)
        alert.notified_utc = None if err else now
        alert.notify_error = err
        alert.notify_count = alert.notify_count + (0 if err else 1)
        db.add(alert)
        db.commit()
        return SilenceCheck(site_id, OPENED, last_seen, quiet_for, threshold, message)

    # Already known silent. This is the branch that stops the flood: the check
    # may run every five minutes, and it says nothing until the quiet period has
    # elapsed.
    if s.silence_renotify_hours <= 0:
        return SilenceCheck(site_id, STILL_SILENT, last_seen, quiet_for, threshold)

    last_notice = as_utc(open_alert.notified_utc)
    since_notice = ((now - last_notice).total_seconds()
                    if last_notice else float("inf"))
    if since_notice < s.silence_renotify_hours * 3600:
        return SilenceCheck(site_id, STILL_SILENT, last_seen, quiet_for, threshold)

    err = _notify(open_alert, message + " Sigue sin reportar.")
    if not err:
        open_alert.notified_utc = now
        open_alert.notify_count += 1
    open_alert.notify_error = err
    db.add(open_alert)
    db.commit()
    return SilenceCheck(site_id, RENOTIFIED, last_seen, quiet_for, threshold, message)


def check_all(db: Session, storage: Storage, site_ids,
              now: Optional[datetime] = None) -> list[SilenceCheck]:
    """Every site. One failing never stops the rest."""
    out: list[SilenceCheck] = []
    for site_id in site_ids:
        try:
            out.append(check_site(db, storage, site_id, now=now))
        except Exception as e:                                  # noqa: BLE001
            log.exception("silence check failed for %s", site_id)
            db.rollback()
            out.append(SilenceCheck(site_id, UNKNOWN, detail=f"check failed: {e}"))
    return out
