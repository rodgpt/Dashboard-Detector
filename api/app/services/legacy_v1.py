"""LEGACY-V1: read the v1 blob layout, speak v2 to everything above.

TEMPORARY, BY DESIGN. The two production units still write v1 and we cannot
deploy to them. This file reads what they actually write and returns the v2
shapes defined in `docs/DATA-CONTRACT.md`, so no router, no response model and
no line of frontend code ever learns that v1 existed.

    Switch to the real thing:   OCEANKIND_CONTRACT_VERSION=2
    Then delete it, in one go:  rm api/app/services/legacy_v1.py
                                grep -rn LEGACY-V1 api/

Every remaining hit is a guard that goes with it. There are five, all of the
shape "if v1: call this file". Nothing else changes.

FOUR THINGS V1 CANNOT GIVE US. They are reported honestly, never invented:

  event_type    never written by v1                  -> "unknown"
  detector      never written, and it was swapped    -> "unknown"
                silently in mid-July, so the history
                spans two populations with no marker
  suppressed    v1 did not omit the flag, it threw    -> false, and the totals
                the events away (F-03). There is no      undercount. Said out
                record to map                            loud in `degraded`
  captured_utc  v1's `timestamp` is upload time,     -> used, and flagged with
                late by the length of the cellular       time_is_upload: true
                upload

Consumers are told, per response, through `contract: {...}`. A dashboard that
renders "unknown" is correct. A dashboard that renders a guess is not.
"""
from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from app.services.storage import Storage

V1_SCHEMA_VERSION = 1

#: What every v1 response carries, so the caller never has to infer the gaps.
CONTRACT_NOTE = {
    "version": 1,
    "normalized_to": 2,
    "unknown_fields": ["event_type", "detector"],
    "time_is_upload": True,
    "suppressed_undercounts": True,
    "note": "v1 source. event_type and detector were never recorded; "
            "suppressed detections were discarded, not flagged; timestamps are "
            "upload time, not capture time.",
}


# ─── plumbing ─────────────────────────────────────────────────────────────────

def _prefix(site: str, root_site: str) -> str:
    """v1 put the first site at the container root and namespaced the second.
    That asymmetry is exactly what v2 removes."""
    return "" if site == root_site else f"{site}/"


def _finite(x: Any) -> Any:
    """v1 did not sanitise non-finite floats. Python emits `Infinity`, which is
    not valid JSON and blanked this dashboard in production once already. Every
    numeric field may be null; that is the contract."""
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: _finite(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_finite(v) for v in x]
    return x


def _load(storage: Storage, path: str) -> Optional[dict]:
    try:
        return _finite(json.loads(storage.get(path)))
    except Exception:
        return None


def _dt(value: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(value))
    except Exception:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _clip_path(audio_url: Any) -> Optional[str]:
    """v1 stored a full URL in the manifest and a bare blob name in the WhatsApp
    deep link, and the dashboard reconciled them by string matching. v2 has one
    representation: container-relative."""
    if not isinstance(audio_url, str) or not audio_url:
        return None
    if "/alerts/" in audio_url:
        return audio_url.split("/alerts/", 1)[1].split("?", 1)[0]
    return audio_url.lstrip("/")


def _event_id(site: str, ts: Any, url: Any) -> str:
    """v1 has no event id, and the browser needs a stable key for `?play=` and
    for list identity. Deterministic, so the same entry keeps the same id on
    every poll instead of churning."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"oceankind|{site}|{ts}|{url}"))


# ─── events ───────────────────────────────────────────────────────────────────

def _to_event(entry: dict, site: str) -> Optional[dict]:
    ts = entry.get("captured_utc") or entry.get("timestamp")
    if _dt(ts) is None:
        return None
    url = entry.get("audio_url")
    score = entry.get("model_proba")
    return {
        "schema_version": 2,
        "site":     site,
        "device":   entry.get("device"),
        "event_id": _event_id(site, ts, url),

        "captured_utc": ts,
        "uploaded_utc": entry.get("uploaded_utc") or ts,

        # never recorded by v1. not guessed.
        "event_type": entry.get("event_type") or "unknown",
        "detector":   entry.get("detector") or "unknown",
        "score":      score if isinstance(score, (int, float)) else None,
        "suppressed": bool(entry.get("suppressed", False)),

        "audio_level": entry.get("audio_level"),
        "peak_db":     entry.get("peak_db"),
        "bearing_deg": None,

        "clip": {
            "path":        _clip_path(url),
            "sample_rate": 48000,
            "channels":    2,
            "duration_s":  5.0,
            "uploaded":    bool(entry.get("clip_uploaded", url is not None)),
        },

        "detector_meta": {
            "v1_decided_by": entry.get("decided_by"),
            "v1_model_label": entry.get("model_label"),
        },
        "_v1": True,
    }


def list_events(storage: Storage, site: str, root_site: str,
                since: Optional[datetime] = None, until: Optional[datetime] = None,
                event_type: Optional[str] = None, min_score: float = 0.0,
                include_suppressed: bool = True,
                limit: int = 50, offset: int = 0) -> dict:
    """Same envelope as the v2 path. One blob read instead of a prefix listing,
    which is what v1 costs and why v2 exists."""
    until = until or datetime.now(timezone.utc)
    since = since or (until - timedelta(days=7))

    doc = _load(storage, f"{_prefix(site, root_site)}manifest.json") or {}
    matched = []
    for entry in doc.get("alerts", []):
        ev = _to_event(entry, site) if isinstance(entry, dict) else None
        if ev is None:
            continue
        captured = _dt(ev["captured_utc"])
        if captured is None or not (since <= captured <= until):
            continue
        if event_type and ev["event_type"] != event_type:
            continue
        if (ev["score"] or 0) < min_score:
            continue
        if not include_suppressed and ev["suppressed"]:
            continue
        matched.append(ev)

    matched.sort(key=lambda e: e["captured_utc"], reverse=True)
    page = matched[offset:offset + limit]
    return {
        "items": page,
        "total": len(matched),
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(page) < len(matched),
        "scanned_blobs": 1,          # honest: the whole history is one file
        "contract": CONTRACT_NOTE,
    }


# ─── rollups ──────────────────────────────────────────────────────────────────

def _to_status(v1: dict, site: str) -> dict:
    """v1 was flat. v2 groups. Nothing is invented; absent means null."""
    threshold = v1.get("current_threshold")
    return {
        "schema_version": 2,
        "site": site,
        "device": v1.get("device"),
        "generated_utc": v1.get("last_seen"),

        "software_version": v1.get("software_version"),
        "last_seen":        v1.get("last_seen"),
        "session_start":    v1.get("session_start"),
        "uptime_seconds":   v1.get("uptime_seconds"),
        "system_uptime_s":  v1.get("system_uptime_s"),

        # v1 had no health surface at all. That absence IS the finding, so it is
        # reported as unknown rather than as healthy (F-01, F-02).
        "health": v1.get("health") or {
            "detector_ok":     None,
            "audio_ok":        None,
            "duty_cycle_pct":  None,
            "clips_dropped":   None,
            "upload_backlog":  None,
            "degraded_reason": "v1 device: no health surface is published",
        },

        # v1 published `current_threshold`, which did not participate in the
        # alert decision (F-09). Passed through, labelled, never presented as
        # the value in force.
        "detection": v1.get("detection") or {
            "detectors":  [],
            "thresholds": {"v1_current_threshold": threshold},
            "cooldown_s": v1.get("current_cooldown"),
            "last_rms":   v1.get("last_rms"),
        },

        "audio": {
            "device":      v1.get("audio_device"),
            "sample_rate": v1.get("sample_rate"),
            "channels":    2,
        },
        "power": {
            "battery_voltage_v": v1.get("battery_voltage_v"),
            "battery_current_a": v1.get("battery_current_a"),
            "panel_voltage_v":   v1.get("panel_voltage_v"),
            "panel_power_w":     v1.get("panel_power_w"),
            "charge_state":      v1.get("charge_state"),
            "charge_state_id":   v1.get("charge_state_id"),
            "yield_today_kwh":   v1.get("yield_today_kwh"),
            "yield_total_kwh":   v1.get("yield_total_kwh"),
            "max_power_today_w": v1.get("max_power_today_w"),
            "system_load_w":     v1.get("system_load_w"),
        },
        "network": {
            "signal_bars":  v1.get("signal_bars"),
            "signal_rssi":  v1.get("signal_rssi"),
            "network_type": v1.get("network_type"),
        },
        "system": {
            "cpu_temp_c":    v1.get("cpu_temp_c"),
            "disk_used_pct": v1.get("disk_used_pct"),
            "disk_free_gb":  v1.get("disk_free_gb"),
            "disk_total_gb": v1.get("disk_total_gb"),
            "ram_used_pct":  v1.get("ram_used_pct"),
            "ram_used_mb":   v1.get("ram_used_mb"),
            "ram_total_mb":  v1.get("ram_total_mb"),
        },
        "contract": CONTRACT_NOTE,
    }


def _to_power(v1: dict, site: str) -> dict:
    history = v1.get("history") or []
    span_h = None
    if len(history) >= 2:
        a, b = _dt(history[0].get("ts")), _dt(history[-1].get("ts"))
        if a and b:
            span_h = round(abs((b - a).total_seconds()) / 3600)
    return {
        "schema_version": 2,
        "site": site,
        "generated_utc": v1.get("updated") or v1.get("generated_utc"),
        "bucket_s": v1.get("bucket_s"),
        "window_h": v1.get("window_h") or span_h,
        # gaps are load-bearing. never backfilled, never densified (R-8.6)
        "history": history,
        "contract": CONTRACT_NOTE,
    }


def read_blob(storage: Storage, path: str, root_site: str,
              sites: Iterable[dict]) -> Optional[dict]:
    """Single entry point for every non-event blob, so the guard upstream is one
    `if`. Returns None when absent, exactly like the v2 path (R-7.3)."""
    if path == "_sites.json":
        # v1 has no site registry; the dashboard hardcoded the table. Rebuilt
        # from configuration so the API contract holds either way.
        return {"schema_version": 2, "generated_utc": None,
                "sites": list(sites), "contract": CONTRACT_NOTE}

    parts = path.split("/")           # sites/{site}/{name}
    if len(parts) != 3 or parts[0] != "sites":
        return None
    site, name = parts[1], parts[2]
    raw = _load(storage, f"{_prefix(site, root_site)}{name}")
    if raw is None:
        return None

    if name == "status.json":
        return _to_status(raw, site)
    if name == "power_history.json":
        return _to_power(raw, site)
    # acoustic_indicators.json and ocean_conditions.json have no device
    # producer in either version. Passed through with the envelope.
    raw.setdefault("schema_version", 2)
    raw.setdefault("site", site)
    raw["contract"] = CONTRACT_NOTE
    return raw


def clip_blob(site: str, path: str, root_site: str) -> str:
    """v1 clips sit beside the manifest, not under a clips/ tree."""
    return f"{_prefix(site, root_site)}{path}"


# ─── storage for a public container ───────────────────────────────────────────

class PublicHttpStorage(Storage):
    """The v1 container is public: `web/static/index.html` fetches it with no
    credential. So we can read live production data today with no client action.
    Read-only, no listing, which the v1 path never needs because every blob has
    a fixed name. That is precisely why v1 could not paginate.

    This goes when the container is made private and v2 lands (F-07)."""

    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/") + "/"

    def list(self, prefix: str):
        raise NotImplementedError("v1 source reads fixed blob names; it never lists")

    def get(self, path: str) -> bytes:
        import urllib.request
        with urllib.request.urlopen(self.base + path, timeout=15) as r:
            return r.read()

    def exists(self, path: str) -> bool:
        import urllib.error
        import urllib.request
        req = urllib.request.Request(self.base + path, method="HEAD")
        try:
            with urllib.request.urlopen(req, timeout=15):
                return True
        except urllib.error.URLError:
            return False
