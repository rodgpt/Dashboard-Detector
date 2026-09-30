"""Device-facing routes. Separate credential from user sessions, so a compromised
browser cannot write (R-6.1)."""
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Response, status
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.models import Device, DeviceStatus, DeviceStatusHistory, as_utc
from app.core.security import verify_password
from app.core.config import settings
from app.services import deviceconfig, indexer
from app.services.storage import get_storage

router = APIRouter()


def _record_push_failure(db: Session, device: Device, reason: str) -> None:
    """Persist a rejection where an operator will see it (D-022).

    A `4xx` returned to a device is invisible: nobody is watching our logs, and
    the device's own health surface reports it is trying. So the rejection is
    stamped on the device row next to `last_seen`, and the admin panel can say
    "this unit's pushes are being refused, and why" without anyone thinking to
    look. Never fail quietly.
    """
    device.last_push_error_utc = datetime.now(timezone.utc)
    # Bounded: this is operator-facing text, not a log sink.
    device.last_push_error = reason[:300]
    db.add(device)
    db.commit()


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


@router.post("/events", status_code=status.HTTP_202_ACCEPTED)
def push_event(payload: Any = Body(...),
               device: Device = Depends(current_device),
               db: Session = Depends(get_session)):
    """**One detection, pushed by the device as it happens** (R-6.3, D-022).

    This is the low-latency path and nothing more. The device writes the event
    blob regardless of what happens here, so a failure costs freshness and never
    an event: the weekly reconcile pass reads the same event out of storage. Any
    change that makes correctness depend on this route has broken the design —
    see `DATA-CONTRACT.md`, **Event upload**.

    **`202` whether or not the event was already indexed.** A duplicate is the
    expected case, not an error: a reconcile pass may have picked the event up
    first, or the device may be retrying after an ambiguous timeout. Returning
    `409` would push the device into tracking what it had successfully sent,
    which is exactly the bookkeeping the unique constraint on `event_id` exists
    to make unnecessary (R-12.3). There is no `409` on this route.

    The document is stored verbatim. No `response_model`, no reshaping, no
    validation beyond the handful of fields the index sorts and filters on — a
    field the device adds must reach the browser, not be quietly dropped on the
    way in, which is the same rule the rollup routes follow.
    """
    # Site scoping. This is containment, not revocation: revoking a compromised
    # unit is deleting its device record, which is immediate and total. This is
    # what bounds the damage in the window before anyone notices, so one stolen
    # key cannot inject detections across the fleet.
    site = payload.get("site") if isinstance(payload, dict) else None
    if site != device.site_id:
        reason = (f"site mismatch: document says {site!r}, "
                  f"device is registered to {device.site_id!r}")
        _record_push_failure(db, device, reason)
        raise HTTPException(status.HTTP_403_FORBIDDEN, reason)

    try:
        created = indexer.index_event(db, payload, via=indexer.VIA_PUSH)
    except indexer.EventRejected as e:
        # Malformed, or a naive `captured_utc`. Re-sending it unchanged will not
        # help, so the device is told to stop retrying this one — and we record
        # why, because a device silently failing to deliver is the failure this
        # whole system exists to notice.
        _record_push_failure(db, device, str(e))
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    device.last_push_utc = datetime.now(timezone.utc)
    db.add(device)
    db.commit()

    # `indexed: false` means "already present", never "rejected". The device
    # treats both as done; this is here so an operator debugging a spool drain
    # can tell a fresh event from a replay.
    return {"indexed": created, "event_id": payload.get("event_id")}


@router.post("/heartbeat", status_code=status.HTTP_202_ACCEPTED)
def heartbeat(payload: dict = Body(...),
             device: Device = Depends(current_device),
             db: Session = Depends(get_session)):
    """**Health/telemetry, pushed every `heartbeat_interval_s`** (`DATA-CONTRACT.md`,
    **Device heartbeat**).

    Not an event: never touches `detection_event`, never goes through the
    indexer, and carries no site-scoping check the way `/events` does — this
    route is per-*device*, not per-*detection*, and `current_device` already
    ties the credential to exactly one device, so there is nothing in the
    payload that determines where this gets filed.

    **Monotonic by `last_seen`, enforced here — not by the device's
    discipline.** The device is built to never retry a failed heartbeat
    (§Device heartbeat: a stale one has no value, and retrying risks
    delivering a late one *after* a fresher one already landed, regressing
    what the dashboard shows). This route accepts an out-of-order or
    duplicate POST without error either way (still `202`: a device must never
    treat this response as something to act on) but silently ignores it if it
    is not newer than what is already stored. That is the second half of the
    "no regression" guarantee — correctness lives here, structurally, not
    only in the device behaving well.

    Two writes, always together: `DeviceStatus` (upserted — what
    `GET /api/sites/{site_id}/status` reads) and `DeviceStatusHistory`
    (append-only — trend queries later). A heartbeat that updated "current"
    without a history row would be a silent gap nothing else could surface.
    """
    reported = payload.get("last_seen") if isinstance(payload, dict) else None
    if not isinstance(reported, str):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "last_seen (ISO 8601) is required")
    try:
        reported_dt = datetime.fromisoformat(reported)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "last_seen must be ISO 8601")
    if reported_dt.tzinfo is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "last_seen must carry a UTC offset")
    reported_dt = as_utc(reported_dt)

    existing = db.get(DeviceStatus, device.id)
    if existing and reported_dt <= as_utc(existing.reported_last_seen):
        return {"accepted": False, "reason": "stale — not newer than the stored reading"}

    now = datetime.now(timezone.utc)
    if existing:
        existing.reported_last_seen = reported_dt
        existing.received_utc = now
        existing.payload = payload
        db.add(existing)
    else:
        db.add(DeviceStatus(device_id=device.id, reported_last_seen=reported_dt,
                            received_utc=now, payload=payload))
    db.add(DeviceStatusHistory(device_id=device.id, reported_last_seen=reported_dt,
                               received_utc=now, payload=payload))
    db.commit()
    return {"accepted": True}
