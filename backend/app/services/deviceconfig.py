"""Device configuration: defaults, clamping, signing and publication (R-6.2).

The client chooses threshold values; we bound them and sign them (D-015). The
tables below implement the ones in `DATA-CONTRACT.md` under **Device
configuration** — change them together or not at all.

**Transport is storage, not HTTP** (D-020). The backend writes
`sites/{site_id}/remote_config.json`; the device polls it every 300 s and
applies a document only when `config_version` differs from the one in force.
`GET /api/devices/config` still exists but is a read-only debugging view and
must return byte-identical content.
"""
import hashlib
import hmac
import json
from datetime import datetime, timezone

# The values in force when nobody has tuned anything.
DEFAULTS: dict = {
    "detection_mode":       "psd",
    "score_min":            0.60,
    "alert_min_rms":        0.010,
    "alert_threshold":      0.08,
    "psd_threshold_db":     8.0,
    "psd_f_min":            55.0,
    "psd_f_max":            1000.0,
    "cooldown_s":           60.0,
    "heartbeat_interval_s": 60.0,
    "window_hop_s":         5.0,
}

# field -> (low, high). Out of range is clamped to the nearest bound and
# reported, never silently accepted and never rejected: a tuning mistake must
# not strand a unit on stale config.
CLAMPS: dict[str, tuple[float, float]] = {
    "score_min":            (0.05, 0.95),
    "alert_min_rms":        (0.0, 0.20),
    "alert_threshold":      (0.005, 0.50),
    "psd_threshold_db":     (3.0, 30.0),
    "psd_f_min":            (20.0, 2000.0),
    "psd_f_max":            (100.0, 20000.0),
    "cooldown_s":           (10.0, 3600.0),
    "heartbeat_interval_s": (30.0, 3600.0),
    # 5.0 is back-to-back windows, the calibrated behaviour. Below 5 they
    # overlap so an event up to 5-h s always lands whole in one window, at
    # CPU cost x(5/h). Measure on the bench before lowering.
    "window_hop_s":         (1.0, 5.0),
}

MODES = ("psd", "rms", "auto")

CONFIG_BLOB = "sites/{site_id}/remote_config.json"


class ConfigError(ValueError):
    """Invalid in a way clamping must not paper over. The message is shown to
    the administrator who typed it."""


def validate_and_clamp(raw: dict) -> tuple[dict, list[str]]:
    """Config in, (clamped config, human-readable adjustment notes) out.

    Unknown keys and malformed values are errors, not omissions: a typo'd key
    that silently failed to tune anything is the quiet failure this system
    exists to remove. Missing keys take defaults, so a partial tune is safe.
    """
    unknown = set(raw) - set(DEFAULTS)
    if unknown:
        raise ConfigError(f"unknown config field(s): {', '.join(sorted(unknown))}")

    cfg = dict(DEFAULTS)
    notes: list[str] = []

    mode = raw.get("detection_mode", DEFAULTS["detection_mode"])
    if mode not in MODES:
        # an enum typo would disable detection; reject, never guess
        raise ConfigError(f"detection_mode must be one of {', '.join(MODES)}")
    cfg["detection_mode"] = mode

    for field, (lo, hi) in CLAMPS.items():
        if field not in raw:
            continue
        try:
            value = float(raw[field])
        except (TypeError, ValueError):
            raise ConfigError(f"{field} must be a number")
        if value != value or value in (float("inf"), float("-inf")):
            raise ConfigError(f"{field} must be finite")
        clamped = min(max(value, lo), hi)
        if clamped != value:
            notes.append(f"{field}: {value:g} fuera de rango [{lo:g}, {hi:g}], ajustado a {clamped:g}")
        cfg[field] = clamped

    # inverted bounds are rejected, not clamped (DATA-CONTRACT.md)
    if cfg["psd_f_min"] >= cfg["psd_f_max"]:
        raise ConfigError("psd_f_min must be below psd_f_max")

    return cfg, notes


def sign(document: dict, key: str) -> str:
    """Hex HMAC-SHA256 over the canonical serialisation of the whole document
    with `signature` excluded: UTF-8, keys sorted, no whitespace.

    The device recomputes exactly this and compares with `compare_digest`. Both
    sides must canonicalise the *same object* — canonicalising different
    subsets is precisely how configuration stops applying with nothing logged.
    """
    body = {k: v for k, v in document.items() if k != "signature"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hmac.new(key.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def build_document(site_id: str, config: dict, config_version: str, key: str,
                   device_id: str | None = None) -> dict:
    """The exact document the contract specifies, signed.

    `device_id` is optional: `None` means the document applies to every device
    at the site, which is the common case. There is no `expires_utc` — a
    configuration stays in force until a different `config_version` verifies.
    Stale and detecting beats fresh and silent.
    """
    doc = {
        "schema_version": 2,
        "config_version": config_version,
        "site": site_id,
        "device_id": device_id,
        "issued_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": config,
    }
    doc["signature"] = sign(doc, key)
    return doc


def serialise(document: dict) -> bytes:
    """What actually gets written. Canonical too, so the bytes in storage and
    the bytes the debugging endpoint returns are identical."""
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode()


def publish(storage, site_id: str, document: dict) -> str:
    """Write the signed document to storage. Returns the blob path."""
    path = CONFIG_BLOB.format(site_id=site_id)
    storage.put(path, serialise(document), "application/json")
    return path
