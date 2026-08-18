"""User, site-assignment and device-credential management. The 'panel de
administración' the presupuesto promises, with no cloud console involved (R-3.3)."""
import re
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlmodel import Session, select, delete

from app.core.db import get_session
from app.core.models import User, SiteAccess, Device
from app.core.security import require_admin, hash_password
from app.services.storage import get_storage

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


def _known_sites() -> list[str]:
    from app.services.events import read_json
    doc = read_json(get_storage(), "_sites.json") or {"sites": []}
    return [s.get("id") for s in doc.get("sites", []) if s.get("id")]


@router.get("/devices", response_model=list[DeviceOut])
def list_devices(_: User = Depends(require_admin), db: Session = Depends(get_session)):
    return list(db.exec(select(Device)))


@router.post("/devices", response_model=DeviceCreated, status_code=201)
def create_device(body: DeviceIn, _: User = Depends(require_admin),
                  db: Session = Depends(get_session)):
    if not _DEVICE_ID.match(body.device_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "device_id must be 3-64 characters: letters, digits, _ or -")
    sites = _known_sites()
    if body.site_id not in sites:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"unknown site '{body.site_id}'; sites are data and this one "
                            f"is not in _sites.json (known: {', '.join(sorted(sites)) or 'none'})")
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
    db.delete(d); db.commit()
