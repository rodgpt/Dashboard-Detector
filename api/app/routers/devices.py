"""Device-facing routes. Separate credential from user sessions, so a compromised
browser cannot write (R-6.1)."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlmodel import Session, select

from app.core.db import get_session
from app.core.models import Device
from app.core.security import verify_password
from app.core.config import settings

router = APIRouter()


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
def device_config(device: Device = Depends(current_device)):
    """Signed and clamped configuration, replacing the unsigned config blob (R-6.2, F-10).

    TODO: sign the payload with OCEANKIND_CONFIG_SIGNING_KEY and clamp every value
    to a safe range before returning. Thresholds are the client's to choose; the
    clamping and the signing are ours.
    """
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "not implemented yet")
