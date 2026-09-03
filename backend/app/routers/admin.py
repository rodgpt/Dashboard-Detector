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
from app.core.models import User, SiteAccess, Device, DeviceConfig, Site
from app.core.security import require_admin, hash_password
from app.core.config import settings
from app.services.storage import get_storage
from app.services import deviceconfig, sites as sites_service

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


class DeviceCreated(DeviceOut):
    key: str            # plaintext, this response only. never stored, never logged


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
    grants = list(db.exec(select(SiteAccess).where(SiteAccess.site_id == site_id)))
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
    return list(db.exec(select(Device)))


@router.post("/devices", response_model=DeviceCreated, status_code=201)
def create_device(body: DeviceIn, _: User = Depends(require_admin),
                  db: Session = Depends(get_session)):
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

    key = secrets.token_urlsafe(32)
    d = Device(device_id=body.device_id, site_id=body.site_id, key_hash=hash_password(key))
    db.add(d); db.commit(); db.refresh(d)
    return DeviceCreated(id=d.id, device_id=d.device_id, site_id=d.site_id,
                         active=d.active, last_seen=d.last_seen, key=key)


@router.delete("/devices/{device_pk}", status_code=204)
def delete_device(device_pk: int, _: User = Depends(require_admin),
                  db: Session = Depends(get_session)):
    """Revocation. The unit gets 401 on its next poll and keeps its last valid
    config, per DATA-CONTRACT.md expiry semantics."""
    d = db.get(Device, device_pk)
    if not d:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such device")
    db.exec(delete(DeviceConfig).where(DeviceConfig.device_id == d.device_id))
    db.delete(d); db.commit()


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
                           **extra)


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
    try:
        config, notes = deviceconfig.validate_and_clamp(body)
    except deviceconfig.ConfigError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    key = settings().config_hmac_key
    if not key:
        # Refuse the whole operation rather than persist something we cannot
        # deliver. Never publish unsigned (R-6.2.1).
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "OCEANKIND_CONFIG_HMAC_KEY is not configured, so this "
                            "configuration cannot be signed or published")

    row = db.exec(select(DeviceConfig)
                  .where(DeviceConfig.device_id == d.device_id)).first()
    if row:
        row.version += 1
        row.config_json = json.dumps(config)
    else:
        row = DeviceConfig(device_id=d.device_id, config_json=json.dumps(config))
    row.updated_utc = datetime.now(timezone.utc)
    db.add(row); db.commit(); db.refresh(row)

    # One blob per site, so a second device at the same site would overwrite
    # this document. Say so instead of silently clobbering it.
    siblings = [x.device_id for x in db.exec(select(Device).where(
        Device.site_id == d.site_id, Device.device_id != d.device_id))]
    warning = (f"site '{d.site_id}' also has {', '.join(siblings)}; the site has one "
               f"configuration blob and this publish replaced it") if siblings else None

    doc = deviceconfig.build_document(
        site_id=d.site_id, config=config, config_version=_config_version(row),
        key=key, device_id=d.device_id)
    path = deviceconfig.publish(get_storage(), d.site_id, doc)

    return _state(d, row, clamp_notes=notes, published_to=path, publish_warning=warning)


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

    r = scheduler.run_once(body.site_id, trigger="manual")
    return ReconcileOut(site_id=r.site_id, newly_indexed=r.newly_indexed,
                        conflicting=r.conflicting, rejected=r.rejected,
                        drift=r.drift, ok=r.ok, error=r.error)
