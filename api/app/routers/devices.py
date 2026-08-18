"""Device-facing routes. Separate credential from user sessions, so a compromised
browser cannot write (R-6.1)."""
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlmodel import Session, select

from app.core.db import get_session
from app.core.models import Device, DeviceConfig
from app.core.security import verify_password
from app.core.config import settings
from app.services import deviceconfig

router = APIRouter()

# expires_utc means *refresh me*, not *stop*: past it, the device keeps the
# config and names the staleness in health.degraded_reason (DATA-CONTRACT.md)
CONFIG_TTL_HOURS = 24


def current_device(x_device_key: str = Header(...), x_device_id: str = Header(...),
                   db: Session = Depends(get_session)) -> Device:
    d = db.exec(select(Device).where(Device.device_id == x_device_id)).first()
    if not d or not d.active or not verify_password(x_device_key, d.key_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid device credentials")
    # provisioning feedback: the panel shows whether a freshly keyed unit ever connected
    d.last_seen = datetime.now(timezone.utc)
    db.add(d); db.commit(); db.refresh(d)
    return d


@router.get("/config")
def device_config(device: Device = Depends(current_device),
                  db: Session = Depends(get_session)):
    """Signed and clamped configuration, replacing the unsigned config blob (R-6.2, F-10).

    Thresholds are the client's to choose; the clamping and the signing are ours
    (D-015). Payload, signature scheme and clamp table are DATA-CONTRACT.md's
    "Device configuration" section; this implements it and nothing beyond it.
    """
    key = settings().config_signing_key
    if not key:
        # loud, and only this route: a missing signing key must not take the
        # dashboard down, but it must never degrade to an unsigned payload
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "config signing key not provisioned on the server")

    row = db.exec(select(DeviceConfig)
                  .where(DeviceConfig.device_id == device.device_id)).first()
    stored = json.loads(row.config_json) if row else deviceconfig.DEFAULTS
    version = row.version if row else 1
    # stored values are already clamped; re-clamp anyway so a hand-edited
    # database row can never reach a device outside its bounds
    config, _ = deviceconfig.validate_and_clamp(stored)

    now = datetime.now(timezone.utc)
    payload = {
        "schema_version": 2,
        "device_id": device.device_id,
        "site": device.site_id,
        "config_version": version,
        "issued_utc": now.isoformat(timespec="seconds"),
        "expires_utc": (now + timedelta(hours=CONFIG_TTL_HOURS)).isoformat(timespec="seconds"),
        "config": config,
    }
    payload["signature"] = deviceconfig.sign(payload, key)
    return payload
