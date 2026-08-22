"""Device-facing routes. Separate credential from user sessions, so a compromised
browser cannot write (R-6.1)."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.models import Device
from app.core.security import verify_password
from app.core.config import settings
from app.services import deviceconfig
from app.services.storage import get_storage

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
    """**Read-only debugging view of the configuration blob** (D-020).

    This is not the delivery path. The device reads
    `sites/{site_id}/remote_config.json` from storage, which the backend writes
    when configuration is tuned. This route exists so an operator can see what a
    unit will receive without opening a storage browser, and it returns the blob
    **byte for byte** — reading it here and reading it from storage must never
    produce two different documents, because that is how a signature mismatch
    hides.

    It deliberately does not compose a document of its own. If the blob is
    absent, that is the honest answer: nothing has been published for this site.
    """
    if not settings().config_hmac_key:
        # Loud, and only on this route. Never a hint that unsigned would do.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "config HMAC key not provisioned on the server")

    path = deviceconfig.CONFIG_BLOB.format(site_id=device.site_id)
    storage = get_storage()
    if not storage.exists(path):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"no configuration has been published for site '{device.site_id}'. "
            "the device keeps its last valid configuration; it does not fall back to defaults")
    return Response(storage.get(path), media_type="application/json")
