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


class Device(SQLModel, table=True):
    """Per-device credential, separate from user sessions (R-6.1)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    device_id: str = Field(index=True, unique=True)
    site_id: str = Field(index=True)
    key_hash: str
    active: bool = True
    last_seen: Optional[datetime] = None
