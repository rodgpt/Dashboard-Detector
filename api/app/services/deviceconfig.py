"""Device configuration: defaults, clamping and signing (R-6.2, F-10, D-014).

The client chooses threshold values; we bound and sign them. The clamp table
below is the implementation of the one in DATA-CONTRACT.md — change them
together or not at all. Clamping happens here, server-side, before signing,
so the device and the operator always see the same number in force.
"""
import hashlib
import hmac
import json

# The values in force when nobody has tuned anything. Same table as
# DATA-CONTRACT.md "Device configuration".
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
}

# field -> (low, high). Out of range is clamped to the nearest bound and
# reported, never silently accepted and never rejected: a tuning mistake must
# not leave the device on stale config.
CLAMPS: dict[str, tuple[float, float]] = {
    "score_min":            (0.05, 0.95),
    "alert_min_rms":        (0.0, 0.20),
    "alert_threshold":      (0.005, 0.50),
    "psd_threshold_db":     (3.0, 30.0),
    "psd_f_min":            (20.0, 2000.0),
    "psd_f_max":            (100.0, 20000.0),
    "cooldown_s":           (10.0, 3600.0),
    "heartbeat_interval_s": (30.0, 3600.0),
}

MODES = ("psd", "rms", "auto")


class ConfigError(ValueError):
    """Invalid in a way clamping must not paper over. The message is shown to
    the administrator who typed it."""


def validate_and_clamp(raw: dict) -> tuple[dict, list[str]]:
    """Full config in, (clamped config, human-readable adjustment notes) out.

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


def sign(payload: dict, key: str) -> str:
    """Hex HMAC-SHA256 over the canonical serialisation, `signature` excluded:
    UTF-8, keys sorted, no whitespace. The device recomputes this exactly."""
    body = {k: v for k, v in payload.items() if k != "signature"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hmac.new(key.encode(), canonical.encode(), hashlib.sha256).hexdigest()
