"""Users, roles and site assignments. SQLite, one file (R-9.2).

Detections live in blob storage. This database holds only who may see what, so it
stays small enough to copy around and portable enough to swap for Postgres by
changing a connection string.
"""
from datetime import datetime, timezone
from typing import Optional
from sqlmodel import SQLModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    password_hash: str                       # argon2. never reversible (R-2.2)
    role: str = "operator"                   # operator | admin (R-3.2)
    active: bool = True
    created_at: datetime = Field(default_factory=_now)


class SiteAccess(SQLModel, table=True):
    """Which users see which sites. Data, not code (R-3.1)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="user.id")
    site_id: str = Field(index=True)


class Site(SQLModel, table=True):
    """The site registry (R-3.1: adding a unit is a data change, not a code one).

    Authoritative here rather than in `_sites.json`, because a registry that can
    only be edited by hand-uploading a blob is not manageable, and on a fresh
    storage container it does not exist at all — which left no way to register
    the first device. `_sites.json` remains a read fallback; see services/sites.py.

    `site_id` is the storage path segment (`sites/{site_id}/...`), so it is the
    natural key and it is what the API returns as `id`.
    """
    site_id: str = Field(primary_key=True)
    name: str
    # Coordinates live here rather than on the device, which is what closes F-08
    # properly. Both nullable: an unsurveyed site is honest, 0,0 is not.
    lat: Optional[float] = None
    lon: Optional[float] = None
    device: Optional[str] = None
    active: bool = True
    created_at: datetime = Field(default_factory=_now)


class Device(SQLModel, table=True):
    """Per-device credential, separate from user sessions (R-6.1)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    device_id: str = Field(index=True, unique=True)
    site_id: str = Field(index=True)
    key_hash: str
    active: bool = True
    last_seen: Optional[datetime] = None


class DeviceConfig(SQLModel, table=True):
    """Tuned configuration per device (R-6.2). Absent row = defaults at version 1.

    `version` is monotonic; the device applies only what is newer than what it
    runs. `config_json` is stored already clamped, so what the panel shows,
    what gets signed and what status.json later reports are the same numbers.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    device_id: str = Field(index=True, unique=True)      # Device.device_id
    config_json: str
    version: int = 2                     # 1 is the implicit defaults version
    updated_utc: datetime = Field(default_factory=_now)
