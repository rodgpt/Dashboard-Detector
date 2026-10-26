"""User, site-assignment and device-credential management. The 'panel de
administración' the presupuesto promises, with no cloud console involved (R-3.3)."""
import json
import re
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlmodel import Session, select, delete, col

from app.core.database import get_session
from app.core.models import (
    User, SiteAccess, Device, DeviceConfig, DeviceStatus, DeviceStatusHistory, Site,
)
from app.core.security import require_admin, hash_password, derive_keys
from app.core.config import settings
from app.services.storage import get_storage
from app.services import deviceconfig, releases, sites as sites_service

router = APIRouter()


class UserIn(BaseModel):
    email: EmailStr
    password: str
    role: str = "operator"
    sites: list[str] = []


class UserOut(BaseModel):
    id: int
    email: str
    role: str
    active: bool
    sites: list[str]


class SitesIn(BaseModel):
    sites: list[str]


def _out(u: User, db: Session) -> UserOut:
    sites = list(db.exec(select(SiteAccess.site_id).where(SiteAccess.user_id == u.id)))
    return UserOut(id=u.id, email=u.email, role=u.role, active=u.active, sites=sites)


@router.get("/users", response_model=list[UserOut])
def list_users(_: User = Depends(require_admin), db: Session = Depends(get_session)):
    return [_out(u, db) for u in db.exec(select(User))]


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserIn, _: User = Depends(require_admin), db: Session = Depends(get_session)):
    if body.role not in ("operator", "admin"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "role must be operator or admin")
    if len(body.password) < 12:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "password must be at least 12 characters")
    if db.exec(select(User).where(User.email == body.email.lower())).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "that email already exists")

    u = User(email=body.email.lower(), password_hash=hash_password(body.password), role=body.role)
    db.add(u); db.commit(); db.refresh(u)
    # Site checkboxes only mean something for an operator: an admin's access is
    # unconditional (assert_site_allowed never consults SiteAccess for them),
    # so a grant recorded here would be inert and, worse, invisible — the users
    # table shows "todos los sitios" for any admin rather than its real rows.
    if body.role != "admin":
        for s in body.sites:
            db.add(SiteAccess(user_id=u.id, site_id=s))
        db.commit()
    return _out(u, db)


@router.put("/users/{user_id}/sites", response_model=UserOut)
def set_sites(user_id: int, body: SitesIn, _: User = Depends(require_admin),
              db: Session = Depends(get_session)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such user")
    if u.role == "admin":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "sites do not apply to an admin account; its access is unconditional")
    db.exec(delete(SiteAccess).where(SiteAccess.user_id == user_id))
    for s in body.sites:
        db.add(SiteAccess(user_id=user_id, site_id=s))
    db.commit()
    return _out(u, db)


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: int, me: User = Depends(require_admin), db: Session = Depends(get_session)):
    if user_id == me.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "cannot delete yourself")
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such user")
    db.exec(delete(SiteAccess).where(SiteAccess.user_id == user_id))
    db.delete(u); db.commit()


# ── devices (R-6.1, D-017) ───────────────────────────────────────────────────
# The key is generated here, returned in the creation response once, and stored
# only as an argon2 hash. There is no way to read it back, by construction: the
# provisioning flow is copy once, paste into /etc/oceankind.env on the bench.

_DEVICE_ID = re.compile(r"^[A-Za-z0-9_-]{3,64}$")


class DeviceIn(BaseModel):
    device_id: str
    site_id: str


class DeviceOut(BaseModel):
    id: int
    device_id: str
    site_id: str
    active: bool
    last_seen: datetime | None
    # Push health (D-022). The contract (`DATA-CONTRACT.md` §Event upload, "What
    # this does not change") promises a refused push is visible in the panel next
    # to `last_seen`. The columns were recorded since 2026-09-03 and exposed by
    # nothing until the 2026-10-24 review (BE-05): an error stamp newer than the
    # success stamp means the push path is broken right now.
    last_push_utc: datetime | None = None
    last_push_error_utc: datetime | None = None
    last_push_error: str | None = None
    # Release state (Rpi-Detector D-021), from the last heartbeat and the
    # assignment. `installed_sha` ≠ the assigned tag's commit after a rollback
    # shows as `failed_sha` set; the panel paints it red.
    software_version: str | None = None
    installed_sha: str | None = None
    installed_release: str | None = None
    failed_sha: str | None = None
    failed_release: str | None = None
    assigned_release: str | None = None
    hold: bool = False
    # Created before D-020 with the global signing key: can still push and
    # heartbeat, but no configuration or release can be signed for it until it
    # is deleted and created again (one new secret to paste on the unit).
    needs_reprovision: bool = False


class DeviceCreated(DeviceOut):
    key: str            # the ONE device secret, plaintext, this response only. never stored, never logged


def _device_out(d: Device, db: Session) -> DeviceOut:
    cfg = db.exec(select(DeviceConfig).where(DeviceConfig.device_id == d.device_id)).first()
    st = db.get(DeviceStatus, d.id) if d.id is not None else None
    payload = (st.payload or {}) if st else {}
    ota = payload.get("ota") or {}
    return DeviceOut(
        id=d.id, device_id=d.device_id, site_id=d.site_id, active=d.active, last_seen=d.last_seen,
        last_push_utc=d.last_push_utc, last_push_error_utc=d.last_push_error_utc,
        last_push_error=d.last_push_error,
        software_version=payload.get("software_version"),
        installed_sha=ota.get("installed_sha"), installed_release=ota.get("installed_release"),
        failed_sha=ota.get("failed_sha"), failed_release=ota.get("failed_release"),
        assigned_release=cfg.release if cfg else None, hold=bool(cfg.hold) if cfg else False,
        needs_reprovision=d.config_key is None,
    )


def _known_sites(db: Session) -> list[str]:
    return sites_service.known_ids(db)


# ── sites (R-3.1) ────────────────────────────────────────────────────────────
# Adding a unit is a data change. Before this existed the only way to add one
# was to hand-upload `_sites.json`, which on a fresh container did not exist at
# all — so no site could be registered and therefore no device either.

SITE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}$")


class SiteIn(BaseModel):
    id: str
    name: str
    lat: float | None = None
    lon: float | None = None
    device: str | None = None
    active: bool = True


class SiteUpdate(BaseModel):
    name: str | None = None
    lat: float | None = None
    lon: float | None = None
    device: str | None = None
    active: bool | None = None


class SitesOut(BaseModel):
    sites: list[dict]
    # "database" = managed here. "storage" = still coming from _sites.json and
    # not yet managed. "empty" = nothing anywhere. Shown in the panel so the
    # distinction is visible rather than guessed.
    source: str


@router.get("/sites", response_model=SitesOut)
def list_sites_admin(_: User = Depends(require_admin), db: Session = Depends(get_session)):
    items, source = sites_service.registry(db)
    return {"sites": items, "source": source}


@router.post("/sites", response_model=dict, status_code=201)
def create_site(body: SiteIn, _: User = Depends(require_admin),
                db: Session = Depends(get_session)):
    if not SITE_ID.match(body.id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "site id must be 2-63 characters: lowercase letters, digits, _ or -, "
                            "starting with a letter or digit. it becomes a storage path segment")
    if db.get(Site, body.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "that site id already exists")
    site = Site(site_id=body.id, name=body.name, lat=body.lat, lon=body.lon,
                device=body.device, active=body.active)
    db.add(site); db.commit(); db.refresh(site)
    return sites_service._as_api(site)


@router.put("/sites/{site_id}", response_model=dict)
def update_site(site_id: str, body: SiteUpdate, _: User = Depends(require_admin),
                db: Session = Depends(get_session)):
    """`site_id` itself is immutable: it is a storage path segment, and renaming
    it would orphan every event, clip and rollup already written under it."""
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such site")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(site, field, value)
    db.add(site); db.commit(); db.refresh(site)
    return sites_service._as_api(site)


@router.delete("/sites/{site_id}", status_code=204)
def delete_site(site_id: str, _: User = Depends(require_admin),
                db: Session = Depends(get_session)):
    """Refuses while anything still points at it. Deleting a site out from under
    a device would leave a credential valid for a site that does not exist."""
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such site")
    devices = list(db.exec(select(Device).where(Device.site_id == site_id)))
    if devices:
        names = ", ".join(d.device_id for d in devices)
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"site still has device(s): {names}. remove them first")
    # Only an operator's grant actually gates anything (assert_site_allowed
    # never consults SiteAccess for an admin), so an admin-held row — however
    # it got there — must never be the thing that keeps a site undeletable.
    grants = list(db.exec(
        select(SiteAccess).join(User, User.id == SiteAccess.user_id)
        .where(SiteAccess.site_id == site_id, User.role != "admin")))
    if grants:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"{len(grants)} user(s) are still assigned to this site")
    db.delete(site); db.commit()


@router.post("/sites/import", response_model=SitesOut)
def import_sites(_: User = Depends(require_admin), db: Session = Depends(get_session)):
    """Seed the table from `_sites.json`. Explicit, never automatic — see
    services/sites.py for why."""
    sites_service.import_from_storage(db)
    items, source = sites_service.registry(db)
    return {"sites": items, "source": source}


@router.get("/devices", response_model=list[DeviceOut])
def list_devices(_: User = Depends(require_admin), db: Session = Depends(get_session)):
    return [_device_out(d, db) for d in db.exec(select(Device))]


@router.post("/devices", response_model=DeviceCreated, status_code=201)
def create_device(body: DeviceIn, _: User = Depends(require_admin),
                  db: Session = Depends(get_session)):
    """Issue the device's ONE secret (Rpi-Detector D-020).

    The secret is shown once in this response and never stored. Two keys are
    derived from it with fixed labels (`security.derive_keys`): the
    authentication key, kept as an argon2 hash, and the configuration signing
    key, kept in clear because this side signs. The device derives the same two
    from the same secret. One paste at provisioning covers both.

    If a fleet default release is set (D-021) the new device is assigned it
    immediately, so a fresh unit cannot drift unnoticed.
    """
    if not _DEVICE_ID.match(body.device_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "device_id must be 3-64 characters: letters, digits, _ or -")
    sites = _known_sites(db)
    if body.site_id not in sites:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"unknown site '{body.site_id}'; register the site first "
                            f"(known: {', '.join(sorted(sites)) or 'none'})")
    if db.exec(select(Device).where(Device.device_id == body.device_id)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "that device_id already exists")

    secret = secrets.token_urlsafe(32)
    auth_key, config_key = derive_keys(secret)
    d = Device(device_id=body.device_id, site_id=body.site_id,
               key_hash=hash_password(auth_key), config_key=config_key)
    db.add(d); db.commit(); db.refresh(d)

    default = releases.fleet_default(db)
    if default:
        row = DeviceConfig(device_id=d.device_id, config_json=json.dumps(dict(deviceconfig.DEFAULTS)),
                           release=default, hold=False, updated_utc=datetime.now(timezone.utc))
        db.add(row); db.commit(); db.refresh(row)
        _publish(d, row, dict(deviceconfig.DEFAULTS), db)

    out = _device_out(d, db)
    return DeviceCreated(**out.model_dump(), key=secret)


@router.delete("/devices/{device_pk}", status_code=204)
def delete_device(device_pk: int, _: User = Depends(require_admin),
                  db: Session = Depends(get_session)):
    """Revocation. The unit gets 401 on its next poll and keeps its last valid
    config, per DATA-CONTRACT.md expiry semantics."""
    d = db.get(Device, device_pk)
    if not d:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such device")
    db.exec(delete(DeviceConfig).where(DeviceConfig.device_id == d.device_id))
    # device_status and device_status_history carry an integer FK to device.id
    # with no ON DELETE CASCADE (see the heartbeat migration): leaving these
    # behind means the device row itself can never be deleted once it has
    # heartbeated once, which is every real device.
    db.exec(delete(DeviceStatusHistory).where(DeviceStatusHistory.device_id == d.id))
    db.exec(delete(DeviceStatus).where(DeviceStatus.device_id == d.id))
    db.delete(d); db.commit()


@router.delete("/devices/{device_pk}/status", status_code=204)
def reset_device_status(device_pk: int, _: User = Depends(require_admin),
                        db: Session = Depends(get_session)):
    """Forget the device's *current* heartbeat reading; history is kept.

    The heartbeat route is monotonic on the device's own `last_seen`. A unit
    whose clock was wrong (a Pi without an RTC booting a year ahead) can leave a
    reading no correct heartbeat will ever beat, and until 2026-10-24 nothing
    could clear it short of deleting the device. The route now refuses
    far-future timestamps, so this is the escape hatch for a reading accepted
    before that, or for a clock that was merely a few minutes fast.
    """
    d = db.get(Device, device_pk)
    if not d:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such device")
    db.exec(delete(DeviceStatus).where(DeviceStatus.device_id == d.id))
    db.commit()


# ── device alerts (R-7.5) ────────────────────────────────────────────────────
# `silence.py` records an outage as a `DeviceAlert` row and notifies through a
# webhook that, in every deployment so far, is not configured — so until the
# 2026-10-24 review the only trace of a dead unit was a WARNING line in a
# container log nobody watches. The rows existed; nothing read them.

class AlertOut(BaseModel):
    id: int
    site_id: str
    kind: str
    opened_utc: datetime
    last_seen_utc: datetime | None
    cleared_utc: datetime | None
    notified_utc: datetime | None
    notify_count: int
    notify_error: str | None
    detail: str | None = None     # degraded reason / battery level, when the kind has one
    open: bool


def alert_out(a) -> AlertOut:
    return AlertOut(id=a.id, site_id=a.site_id, kind=a.kind, opened_utc=a.opened_utc,
                    last_seen_utc=a.last_seen_utc, cleared_utc=a.cleared_utc,
                    notified_utc=a.notified_utc, notify_count=a.notify_count,
                    notify_error=a.notify_error, detail=a.detail, open=a.cleared_utc is None)


@router.get("/alerts", response_model=list[AlertOut])
def list_alerts(open_only: bool = True, limit: int = 50,
                _: User = Depends(require_admin), db: Session = Depends(get_session)):
    """Open device alerts across every site (admin). Newest first. `open_only=false`
    also returns cleared ones, for the outage history."""
    from app.core.models import DeviceAlert
    q = select(DeviceAlert)
    if open_only:
        q = q.where(DeviceAlert.cleared_utc == None)              # noqa: E711
    q = q.order_by(col(DeviceAlert.opened_utc).desc()).limit(max(1, min(limit, 500)))
    return [alert_out(a) for a in db.exec(q)]


# ── device configuration tuning (R-6.2, D-015) ───────────────────────────────
# The client tunes thresholds here, without a firmware update. Values are
# clamped on write and the adjusted result is returned, so what the panel
# shows is exactly what the device will be told.

class DeviceConfigOut(BaseModel):
    device_id: str
    site_id: str
    version: int                  # internal counter. rendered into config_version
    config_version: str           # what the device compares. changes on every tune
    is_default: bool              # true until the first tune is saved
    updated_utc: datetime | None
    config: dict
    clamp_notes: list[str] = []   # non-empty when a submitted value was bounded
    published_to: str | None = None   # blob path, once written
    publish_warning: str | None = None
    release: str | None = None    # D-021: assigned release tag, if any
    hold: bool = False


def _get_device(device_pk: int, db: Session) -> Device:
    d = db.get(Device, device_pk)
    if not d:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such device")
    return d


def _config_version(row: DeviceConfig) -> str:
    """The contract wants an opaque string that changes when the config changes.
    Date plus the monotonic counter reads well in a blob and cannot repeat."""
    return f"{row.updated_utc:%Y-%m-%d}-{row.version:02d}"


def _state(d: Device, row: DeviceConfig | None, **extra) -> DeviceConfigOut:
    if row is None:
        return DeviceConfigOut(device_id=d.device_id, site_id=d.site_id, version=1,
                               config_version="default", is_default=True,
                               updated_utc=None, config=dict(deviceconfig.DEFAULTS), **extra)
    return DeviceConfigOut(device_id=d.device_id, site_id=d.site_id, version=row.version,
                           config_version=_config_version(row), is_default=False,
                           updated_utc=row.updated_utc, config=json.loads(row.config_json),
                           release=row.release, hold=bool(row.hold), **extra)


def _require_config_key(d: Device) -> str:
    """A device created before D-020 has no per-device signing key. Say so,
    rather than sign with a key the unit does not hold."""
    if not d.config_key:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"device '{d.device_id}' was created before per-device keys (D-020) and has no "
            "signing key. Delete it and create it again, then paste the new secret into "
            "/etc/oceankind.env on the unit")
    return d.config_key


def _publish(d: Device, row: DeviceConfig, config: dict, db: Session) -> str:
    """Sign the device's document with ITS key, remember the exact bytes on the
    row (what GET /api/devices/config returns), and write the site blob."""
    doc = deviceconfig.build_document(
        site_id=d.site_id, config=config, config_version=_config_version(row),
        key=_require_config_key(d), device_id=d.device_id,
        release=row.release, hold=bool(row.hold))
    row.signed_json = deviceconfig.serialise(doc).decode()
    db.add(row); db.commit(); db.refresh(row)
    return deviceconfig.publish(get_storage(), d.site_id, doc)


def _row_for(d: Device, db: Session, create: bool) -> DeviceConfig | None:
    row = db.exec(select(DeviceConfig).where(DeviceConfig.device_id == d.device_id)).first()
    if row is None and create:
        row = DeviceConfig(device_id=d.device_id, config_json=json.dumps(dict(deviceconfig.DEFAULTS)),
                           updated_utc=datetime.now(timezone.utc))
    return row


@router.get("/devices/{device_pk}/config", response_model=DeviceConfigOut)
def get_device_config(device_pk: int, _: User = Depends(require_admin),
                      db: Session = Depends(get_session)):
    d = _get_device(device_pk, db)
    row = db.exec(select(DeviceConfig)
                  .where(DeviceConfig.device_id == d.device_id)).first()
    return _state(d, row)


@router.put("/devices/{device_pk}/config", response_model=DeviceConfigOut)
def put_device_config(device_pk: int, body: dict, _: User = Depends(require_admin),
                      db: Session = Depends(get_session)):
    """Tune, then publish.

    Full replace. Missing fields take defaults; unknown fields are an error,
    because a typo'd key that silently tuned nothing is a quiet failure.

    The saved values are then written to `sites/{site_id}/remote_config.json`,
    signed. That blob is the delivery path (D-020) — saving without publishing
    would leave the panel showing a configuration no device will ever apply.
    """
    d = _get_device(device_pk, db)
    _require_config_key(d)
    try:
        config, notes = deviceconfig.validate_and_clamp(body)
    except deviceconfig.ConfigError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    row = _row_for(d, db, create=True)
    if row.id is not None:
        row.version += 1
    row.config_json = json.dumps(config)
    row.updated_utc = datetime.now(timezone.utc)
    db.add(row); db.commit(); db.refresh(row)

    # One blob per site, so a second device at the same site would overwrite
    # this document in storage (each device's own copy stays on its row and is
    # what GET /api/devices/config serves). Say so instead of silently clobbering it.
    siblings = [x.device_id for x in db.exec(select(Device).where(
        Device.site_id == d.site_id, Device.device_id != d.device_id))]
    warning = (f"site '{d.site_id}' also has {', '.join(siblings)}; the site has one "
               f"configuration blob and this publish replaced it") if siblings else None

    path = _publish(d, row, config, db)
    return _state(d, row, clamp_notes=notes, published_to=path, publish_warning=warning)


# ── releases (Rpi-Detector D-021) ────────────────────────────────────────────
# Publish a version, then choose which units take it and when. The assignment
# travels in the signed configuration the unit already polls; the unit's OTA
# converges to the assigned tag and never tracks a branch.

class ReleaseAssign(BaseModel):
    release: Optional[str] = None     # git tag; null = no assignment (unit keeps what it runs)
    hold: Optional[bool] = None       # true freezes the unit regardless of release


class ReleasesOut(BaseModel):
    tags: list[str]                   # from GitHub, newest first; empty if unreachable
    fleet_default: Optional[str]


class FleetDefaultIn(BaseModel):
    release: Optional[str]


@router.get("/releases", response_model=ReleasesOut)
def list_releases(refresh: bool = False, _: User = Depends(require_admin),
                  db: Session = Depends(get_session)):
    """`?refresh=true` asks GitHub now instead of serving the 5-minute cache —
    the panel sends it when the assignment row opens."""
    return ReleasesOut(tags=releases.github_tags(refresh=refresh),
                       fleet_default=releases.fleet_default(db))


@router.put("/releases/default", response_model=ReleasesOut)
def set_fleet_default(body: FleetDefaultIn, _: User = Depends(require_admin),
                      db: Session = Depends(get_session)):
    """The release a NEW device is assigned at creation. Does not touch
    existing assignments — staging is per device, on purpose."""
    if not releases.valid_tag(body.release):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "release must be a git tag like v2.2.0")
    releases.set_fleet_default(db, body.release)
    return ReleasesOut(tags=releases.github_tags(), fleet_default=releases.fleet_default(db))


@router.put("/devices/{device_pk}/release", response_model=DeviceConfigOut)
def assign_release(device_pk: int, body: ReleaseAssign, _: User = Depends(require_admin),
                   db: Session = Depends(get_session)):
    """Assign a release and/or set the hold for one device, then re-sign and
    re-publish its configuration so the unit sees it at its next poll."""
    d = _get_device(device_pk, db)
    _require_config_key(d)
    if "release" in body.model_fields_set and not releases.valid_tag(body.release):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "release must be a git tag like v2.2.0")
    row = _row_for(d, db, create=True)
    if "release" in body.model_fields_set:
        row.release = body.release
    if body.hold is not None:
        row.hold = body.hold
    if row.id is not None:
        row.version += 1
    row.updated_utc = datetime.now(timezone.utc)
    db.add(row); db.commit(); db.refresh(row)
    path = _publish(d, row, json.loads(row.config_json), db)
    return _state(d, row, published_to=path)


# ── the detection index: drift, reconcile, rebuild (R-12.2, R-12.5) ──────────
#
# The index is derived and must be *provably* derived. These three routes are
# what make that checkable by a person rather than an assertion in a document:
# what the drift is, when the pass last ran, and a way to rebuild from the
# container and see the same answers come back.

class IndexDayOut(BaseModel):
    day: str
    blobs_in_storage: int
    indexed: int
    drift: int


class IndexSiteOut(BaseModel):
    site_id: str
    window_days: int
    since: str
    until: str
    blobs_in_storage: int
    indexed: int
    drift: int
    days_with_drift: list[IndexDayOut]
    # Null means the pass has never run for this site. Shown rather than
    # smoothed over: an index with zero drift that has never been checked is not
    # the same as one that was checked an hour ago, and only one of them is
    # evidence of anything.
    last_run_utc: Optional[str] = None
    last_run_ok: Optional[bool] = None
    last_run_error: Optional[str] = None
    last_run_trigger: Optional[str] = None


@router.get("/index", response_model=list[IndexSiteOut])
def index_status(_: User = Depends(require_admin), db: Session = Depends(get_session)):
    """Drift per site and per day, plus when the pass last ran (R-12.5).

    Read-only and cheap: it lists blob *names* and runs one query per site. It
    opens no blob and indexes nothing, which is what makes it safe to call from
    a panel that refreshes.

    Non-zero drift is a fault, not a statistic. It means events exist in storage
    that the dashboard will not show — the same failure as a device reporting
    itself healthy while deaf, and the reason this is a screen rather than a log
    line.
    """
    from app.core.models import IndexerRun
    from app.services.reconcile import measure_drift
    from app.services.sites import registry

    items, _source = registry(db)
    out: list[IndexSiteOut] = []
    for site in items:
        site_id = site.get("id")
        if not site_id:
            continue
        r = measure_drift(db, get_storage(), site_id,
                          days=settings().reconcile_window_days)
        last = db.exec(select(IndexerRun)
                       .where(IndexerRun.site_id == site_id)
                       .order_by(col(IndexerRun.started_utc).desc())).first()
        out.append(IndexSiteOut(
            site_id=site_id,
            window_days=settings().reconcile_window_days,
            since=r.since.isoformat(), until=r.until.isoformat(),
            blobs_in_storage=r.blobs_in_storage,
            indexed=sum(d.already_indexed for d in r.days),
            drift=r.drift,
            days_with_drift=[
                IndexDayOut(day=d.day.isoformat(), blobs_in_storage=d.blobs_in_storage,
                            indexed=d.already_indexed, drift=d.drift)
                for d in r.days_with_drift],
            last_run_utc=last.started_utc.isoformat() if last else None,
            last_run_ok=last.ok if last else None,
            last_run_error=last.error if last else None,
            last_run_trigger=last.trigger if last else None,
        ))
    return out


class ReconcileOut(BaseModel):
    site_id: str
    newly_indexed: int
    conflicting: int
    rejected: int
    drift: int
    ok: bool
    error: Optional[str] = None


@router.post("/index/reconcile", response_model=list[ReconcileOut])
def run_reconcile(site_id: Optional[str] = None,
                  _: User = Depends(require_admin),
                  db: Session = Depends(get_session)):
    """Run the pass now, for one site or all of them.

    Safe to press twice: every write goes through the indexer, which is
    idempotent on `event_id` (R-12.3). It does not replace the timer — it exists
    so somebody investigating drift can act on it without waiting a day.
    """
    from app.services import scheduler
    runs = ([scheduler.run_once(site_id, trigger="manual")] if site_id
            else scheduler.run_all(trigger="manual"))
    return [ReconcileOut(site_id=r.site_id, newly_indexed=r.newly_indexed,
                         conflicting=r.conflicting, rejected=r.rejected,
                         drift=r.drift, ok=r.ok, error=r.error) for r in runs]


class RebuildIn(BaseModel):
    site_id: str
    # Typing the site id is the whole guard. This drops rows deliberately, and a
    # destructive action that needs no confirmation is one somebody performs by
    # accident while looking at something else.
    confirm_site_id: str


@router.post("/index/rebuild", response_model=ReconcileOut)
def rebuild_index(body: RebuildIn, _: User = Depends(require_admin),
                  db: Session = Depends(get_session)):
    """Drop this site's index rows and rebuild them from object storage (R-12.2).

    **This is the proof that the index is derived.** If a rebuild cannot
    reproduce it, then something existed only in Postgres and the index had
    quietly become a second source of truth — the exact thing D-021 rules out.
    Worth running deliberately every so often, not only when something looks
    wrong.

    Losing these rows costs a pass, never a detection: object storage is the
    record and every row here came from a blob that is still there.

    **The pass that follows covers the whole history, not the trailing window.**
    Until 2026-10-24 it reconciled only `reconcile_window_days`, so a rebuild on
    any site with more than a fortnight of events quietly threw the rest away —
    and drift read zero afterwards, because drift is measured over the same
    window (review BE-01). `scheduler.run_once(full=True)` lists the `events/`
    prefix to find the oldest day and reconciles from there.
    """
    from app.core.models import DetectionEvent
    from app.services import scheduler

    if body.confirm_site_id != body.site_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "confirm_site_id must match site_id")

    rows = db.exec(select(DetectionEvent)
                   .where(DetectionEvent.site_id == body.site_id)).all()
    for row in rows:
        db.delete(row)
    db.commit()

    r = scheduler.run_once(body.site_id, trigger="rebuild", full=True)
    return ReconcileOut(site_id=r.site_id, newly_indexed=r.newly_indexed,
                        conflicting=r.conflicting, rejected=r.rejected,
                        drift=r.drift, ok=r.ok, error=r.error)
