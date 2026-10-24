"""Every alert a human receives leaves from here (Rpi-Detector D-020).

The device used to call Twilio itself for detections, heartbeats, battery and
degradation, with the account credentials in its env file — the credential that
leaked once (F-04) and that a stolen SD card yields in clear. Everything those
alerts need already reaches the backend: detections by push (D-022), health and
battery by heartbeat (D-018), and absence by the silence watcher — the one alert
a dead device can never send about itself. So the backend is the only sender,
with the one Twilio credential, and the device sends nothing to anyone.

What is sent, and when
----------------------
- **Detection** — a non-suppressed event arrives by push. WhatsApp to ALERT_TO
  with the `?play=` link. Suppressed events (device-side cooldown) are recorded,
  not announced — same rule as before, now enforced here.
- **Cluster** — several detections at one site inside `call_cluster_window_s`:
  a voice call to CALL_TO, at most once per `call_cooldown_s`. Counts suppressed
  events too, exactly as the device did.
- **Silence / recovery** — from `services/silence.py`, via `ops_message`.
- **Degraded / recovered** — `health.degraded_reason` changes between two
  heartbeats. One open `DeviceAlert(kind="degraded")` per site: notified when it
  opens, when the reason text changes, and when it clears.
- **Battery** — `power.battery_voltage_v` crosses a threshold for
  `battery_debounce_heartbeats` consecutive heartbeats, with hysteresis
  (recovery above `battery_recovery_v`). Same numbers the device used.
- **Heartbeat message** — every `alert_heartbeat_hours`, to TECH_TO, one per
  site: "still alive", battery, panel, signal, uptime, audio status.

Transport
---------
Twilio's REST API over plain `urllib` with basic auth — no SDK dependency, no
cloud-specific runtime (R-1). WhatsApp messages use the approved content
templates (`wa_tpl_*`), so every message body is a template plus variables; the
heartbeat template is the one with a free-text slot and carries every
operational message. Without SID, token and sender the transport is
**log-only**: nothing is sent, everything is logged and recorded, and
`/api/health` says `alerts: log-only`.

Sends never run on a request path. Routes `enqueue()` work and a daemon thread
drains it; a Twilio timeout (15 s) therefore cannot slow a heartbeat. Tests call
`drain()` to run the queue inline.
"""
from __future__ import annotations

import base64
import json
import logging
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timezone
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from app.core.config import settings
from app.core.models import DeviceAlert, Site

log = logging.getLogger(__name__)

TWILIO_TIMEOUT_S = 15
TYPE_LABEL = {"vessel": "EMBARCACIÓN", "blast": "DETONACIÓN", "unknown": "RUIDO FUERTE"}


# ── transport ────────────────────────────────────────────────────────────────

def transport() -> str:
    s = settings()
    if not s.alerts_enabled:
        return "off"
    if s.twilio_sid and s.twilio_token and s.twilio_from:
        return "twilio"
    return "log-only"


def _list(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]


def recipients(kind: str) -> list[str]:
    """`alert` → ALERT_TO; anything else → TECH_TO, falling back to ALERT_TO."""
    s = settings()
    if kind == "alert":
        return _list(s.alert_to)
    return _list(s.tech_to) or _list(s.alert_to)


def _twilio_post(path: str, form: dict) -> None:
    s = settings()
    url = f"https://api.twilio.com/2010-04-01/Accounts/{s.twilio_sid}/{path}.json"
    data = urllib.parse.urlencode(form).encode()
    auth = base64.b64encode(f"{s.twilio_sid}:{s.twilio_token}".encode()).decode()
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "oceankind-backend/2.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=TWILIO_TIMEOUT_S) as resp:
            resp.read()
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read(300).decode("utf-8", errors="replace")
        except Exception:                                   # noqa: BLE001
            pass
        raise RuntimeError(f"twilio {exc.code}: {body or exc.reason}") from None


def send_whatsapp(content_sid: str, variables: dict, to: list[str]) -> Optional[str]:
    """One template message to each recipient. Returns an error string if it
    reached nobody, None otherwise. Log-only transport logs and returns None."""
    mode = transport()
    text = json.dumps(variables, ensure_ascii=False)
    if mode != "twilio":
        log.warning("ALERT (%s, not sent): tpl=%s vars=%s to=%s", mode, content_sid, text, to)
        return None
    if not to:
        log.error("ALERT not sent: no recipients configured (ALERT_TO / TECH_TO)")
        return "no recipients configured"
    s = settings()
    sent, last_err = 0, None
    for number in to:
        try:
            _twilio_post("Messages", {"From": s.twilio_from, "To": number,
                                      "ContentSid": content_sid, "ContentVariables": text})
            sent += 1
        except Exception as exc:                            # noqa: BLE001
            last_err = f"{type(exc).__name__}: {exc}"[:300]
            log.warning("WhatsApp to %s failed: %s", number, last_err)
    return None if sent else (last_err or "send failed")


def place_call(to: list[str], twiml: str) -> Optional[str]:
    mode = transport()
    if mode != "twilio":
        log.warning("CALL (%s, not placed): to=%s", mode, to)
        return None
    s = settings()
    if not to or not s.call_from:
        return "no call recipients or CALL_FROM configured"
    last_err = None
    for number in to:
        try:
            _twilio_post("Calls", {"From": s.call_from, "To": number, "Twiml": twiml})
        except Exception as exc:                            # noqa: BLE001
            last_err = f"{type(exc).__name__}: {exc}"[:300]
            log.warning("call to %s failed: %s", number, last_err)
    return last_err


# ── template variables (same scheme the device used) ────────────────────────

def fmt_local(dt: Optional[datetime] = None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    d = dt or datetime.now(timezone.utc)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    try:
        return d.astimezone(ZoneInfo(settings().site_tz)).strftime(fmt)
    except Exception:                                       # noqa: BLE001
        return d.strftime(fmt)


def wa_vars(station: str, *values, prefix_v2: bool = True) -> dict:
    """v3 templates put the station in {{1}}; v2 prefixes it onto the first value."""
    vals = [str(v) for v in values]
    if settings().wa_tpl_version == "3":
        vals = [station] + vals
    elif prefix_v2 and vals:
        vals[0] = f"{station} · {vals[0]}"
    return {str(i + 1): v for i, v in enumerate(vals)}


def station_name(db: Optional[Session], site_id: str) -> str:
    if db is not None:
        try:
            row = db.get(Site, site_id)
            if row and row.name:
                return row.name
        except Exception:                                   # noqa: BLE001
            pass
    return site_id


# ── the queue: nothing here runs on a request path ──────────────────────────

_q: "queue.Queue[tuple[Callable, tuple]]" = queue.Queue(maxsize=500)
_worker: Optional[threading.Thread] = None
_dropped = 0


def enqueue(fn: Callable, *args) -> None:
    global _dropped
    try:
        _q.put_nowait((fn, args))
    except queue.Full:
        _dropped += 1
        log.error("alert queue full — dropped %s (%d dropped so far)", getattr(fn, "__name__", fn), _dropped)


def _run_one(item) -> None:
    fn, args = item
    try:
        fn(*args)
    except Exception:                                       # noqa: BLE001
        log.exception("alert job %s failed", getattr(fn, "__name__", fn))


def start_worker() -> None:
    """Daemon thread that drains the queue. Started from the app lifespan."""
    global _worker
    if _worker and _worker.is_alive():
        return

    def loop():
        while True:
            _run_one(_q.get())

    _worker = threading.Thread(target=loop, name="alerts", daemon=True)
    _worker.start()


def drain() -> int:
    """Run every queued job inline. For tests and for shutdown."""
    n = 0
    while True:
        try:
            item = _q.get_nowait()
        except queue.Empty:
            return n
        _run_one(item)
        n += 1


# ── operational messages (silence, degraded, battery, heartbeat) ─────────────

def ops_message(station: str, text: str, *, sync: bool = False) -> Optional[str]:
    """A free-text operational message to TECH_TO, through the heartbeat
    template's free slot. `sync=True` sends now and returns the error string
    (silence.py records it on the alert row); otherwise it is queued."""
    s = settings()
    variables = wa_vars(station, fmt_local(), "n/d", "n/d", "n/d", text)
    if sync:
        return send_whatsapp(s.wa_tpl_heartbeat, variables, recipients("tech"))
    enqueue(send_whatsapp, s.wa_tpl_heartbeat, variables, recipients("tech"))
    return None


# ── detections and the cluster call ─────────────────────────────────────────

_recent: dict[str, deque] = {}
_last_call: dict[str, float] = {}


def _detection_message(station: str, event: dict) -> None:
    s = settings()
    meta = event.get("detector_meta") or {}
    label = meta.get("label") or TYPE_LABEL.get(str(event.get("event_type")), "DETECCIÓN")
    captured = event.get("captured_utc")
    try:
        when = fmt_local(datetime.fromisoformat(captured), "%H:%M:%S") if captured else fmt_local(fmt="%H:%M:%S")
    except ValueError:
        when = str(captured)
    rms = event.get("audio_level")
    score = event.get("score")
    conf = f"{float(score) * 100:.1f}%" if isinstance(score, (int, float)) else "n/d"
    clip = event.get("clip") or {}
    url = s.dashboard_url or "n/d"
    if s.dashboard_url and clip.get("uploaded") and clip.get("path"):
        url = f"{s.dashboard_url.rstrip('/')}/?play={urllib.parse.quote(str(clip['path']), safe='')}"
    send_whatsapp(s.wa_tpl_alert, wa_vars(
        station, label, when, f"{float(rms):.4f}" if isinstance(rms, (int, float)) else "n/d", conf, url,
    ), recipients("alert"))


def _cluster_call(station: str) -> None:
    s = settings()
    twiml = (
        '<Response>'
        '<Say voice="Polly.Lupe" language="es-MX">'
        f'Alerta del sistema acústico Mar Futura. Se registraron múltiples detecciones '
        f'en pocos minutos en {station}. '
        'Revisa el panel y coordina fiscalización según corresponda.'
        '</Say>'
        '<Pause length="1"/>'
        '<Say voice="Polly.Lupe" language="es-MX">'
        'Repito: múltiples detecciones acústicas. Atención.'
        '</Say>'
        '</Response>'
    )
    err = place_call(_list(s.call_to), twiml)
    if err:
        log.error("cluster call for %s failed: %s", station, err)


def on_event(db: Optional[Session], site_id: str, event: dict) -> None:
    """Called by the push route after an event is indexed for the first time.
    Non-blocking: the message is queued. Every event counts toward the cluster,
    suppressed ones included (the device did the same)."""
    station = station_name(db, site_id)
    s = settings()
    now = time.monotonic()
    recent = _recent.setdefault(site_id, deque())
    recent.append(now)
    while recent and recent[0] < now - s.call_cluster_window_s:
        recent.popleft()
    if len(recent) >= s.call_cluster_count and now - _last_call.get(site_id, 0.0) >= s.call_cooldown_s:
        _last_call[site_id] = now
        log.warning("cluster: %d detections at %s within %.0f s — placing voice call",
                    len(recent), site_id, s.call_cluster_window_s)
        enqueue(_cluster_call, station)
    if not event.get("suppressed"):
        enqueue(_detection_message, station, event)


# ── heartbeat transitions: degraded / battery ───────────────────────────────

_battery_state: dict[int, dict] = {}            # device pk → {pending, count, alerted}
_LEVEL_ORDER = {"warning": 1, "critical": 2, "emergency": 3}


def _open_alert(db: Session, site_id: str, kind: str) -> Optional[DeviceAlert]:
    return db.exec(
        select(DeviceAlert)
        .where(DeviceAlert.site_id == site_id, DeviceAlert.kind == kind)
        .where(DeviceAlert.cleared_utc == None)              # noqa: E711
    ).first()


def _ops_now(station: str, text: str) -> None:
    ops_message(station, text, sync=True)


def _notify_row(row: DeviceAlert, station: str, text: str, now: datetime) -> None:
    """Record the attempt on the row (so a failed send is visible) and queue it."""
    row.notified_utc = now
    row.notify_count = (row.notify_count or 0) + 1
    enqueue(_ops_now, station, text)


def _degraded_transition(db: Session, site_id: str, station: str,
                         prev: Optional[str], cur: Optional[str], now: datetime) -> None:
    row = _open_alert(db, site_id, "degraded")
    if cur and (not prev or cur != prev):
        if row is None:
            row = DeviceAlert(site_id=site_id, kind="degraded", opened_utc=now, last_seen_utc=now)
        row.detail = cur[:300]
        row.last_seen_utc = now
        text = f"⚠️ DEGRADADO: {cur}" if not prev else f"⚠️ DEGRADADO (cambió): {cur}"
        _notify_row(row, station, text, now)
        db.add(row)
    elif prev and not cur and row is not None:
        row.cleared_utc = now
        _notify_row(row, station, "✅ RECUPERADO: el equipo volvió a estado normal", now)
        db.add(row)


def _battery_level(v: float) -> str:
    s = settings()
    if v >= s.battery_recovery_v:
        return "recovered"
    if v <= s.battery_emergency_v:
        return "emergency"
    if v <= s.battery_critical_v:
        return "critical"
    if v <= s.battery_warning_v:
        return "warning"
    return "normal"


def _battery_transition(db: Session, device_pk: int, site_id: str, station: str,
                        payload: dict, now: datetime) -> None:
    s = settings()
    power = payload.get("power") or {}
    v = power.get("battery_voltage_v")
    if not isinstance(v, (int, float)):
        return
    level = _battery_level(float(v))
    st = _battery_state.setdefault(device_pk, {"pending": None, "count": 0, "alerted": None})
    if level == "normal":
        st.update(pending=None, count=0)
        return
    st["count"] = st["count"] + 1 if st["pending"] == level else 1
    st["pending"] = level
    if st["count"] < s.battery_debounce_heartbeats:
        return
    row = _open_alert(db, site_id, "battery")
    if level == "recovered":
        if st["alerted"] is not None or row is not None:
            if row is not None:
                row.cleared_utc = now
                _notify_row(row, station, f"🔋 Batería recuperada ({float(v):.2f} V)", now)
                db.add(row)
            st["alerted"] = None
        return
    if _LEVEL_ORDER[level] <= _LEVEL_ORDER.get(st["alerted"] or "", 0):
        return
    st["alerted"] = level
    panel_w = power.get("panel_power_w") or 0
    load_w = power.get("system_load_w") or 4.0
    net_draw = max(0.1, float(load_w) - float(panel_w))
    remaining = max(0.0, (float(v) - 10.5) / (12.6 - 10.5))
    hours_left = remaining * 180 / net_draw
    eta = f"{hours_left:.1f} h" if hours_left < 24 else f"{hours_left / 24:.1f} días"
    label = {"warning": "BAJA", "critical": "CRITICA", "emergency": "EMERGENCIA"}[level]
    action = (f"La estación se apagará en minutos si no llega sol (autonomía ~{eta})."
              if level == "emergency"
              else f"Revisar paneles y orientación; considerar carga manual (autonomía ~{eta}).")
    if row is None:
        row = DeviceAlert(site_id=site_id, kind="battery", opened_utc=now, last_seen_utc=now)
    row.detail = f"{label} {float(v):.2f} V"
    row.last_seen_utc = now
    row.notified_utc = now
    row.notify_count = (row.notify_count or 0) + 1
    db.add(row)
    enqueue(send_whatsapp, s.wa_tpl_battery,
            wa_vars(station, f"{float(v):.2f}", label, action, prefix_v2=False), recipients("tech"))


def on_heartbeat(db: Session, device_pk: int, site_id: str,
                 prev_payload: Optional[dict], payload: dict) -> None:
    """Called by the heartbeat route after an accepted heartbeat. Writes alert
    rows on the caller's session (committed by the caller) and queues sends."""
    now = datetime.now(timezone.utc)
    station = station_name(db, site_id)
    prev_reason = ((prev_payload or {}).get("health") or {}).get("degraded_reason")
    cur_reason = (payload.get("health") or {}).get("degraded_reason")
    _degraded_transition(db, site_id, station, prev_reason, cur_reason, now)
    _battery_transition(db, device_pk, site_id, station, payload, now)


# ── the periodic heartbeat message ───────────────────────────────────────────

def _fmt_uptime(seconds) -> str:
    if not isinstance(seconds, (int, float)):
        return "?"
    sec = int(seconds)
    d, rem = divmod(sec, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    return f"{d}d {h}h {m}m" if d else f"{h}h {m}m"


def heartbeat_message(station: str, payload: dict) -> None:
    s = settings()
    power = payload.get("power") or {}
    net = payload.get("network") or {}
    health = payload.get("health") or {}
    audio = ("🎙️ grabando OK" if health.get("audio_ok") is not False and health.get("capture_ok") is not False
             else "⚠️ SIN AUDIO — revisar hidrófono/captura")
    bars = net.get("signal_bars")
    send_whatsapp(s.wa_tpl_heartbeat, wa_vars(
        station, fmt_local(),
        power.get("battery_voltage_v", "n/d") if power.get("battery_voltage_v") is not None else "n/d",
        power.get("panel_power_w", "n/d") if power.get("panel_power_w") is not None else "n/d",
        int(bars) if isinstance(bars, (int, float)) else "n/d",
        f"{_fmt_uptime(payload.get('uptime_seconds'))}  ·  {audio}",
    ), recipients("tech"))
