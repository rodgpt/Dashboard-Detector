"""Users, roles, site assignments, sites and device records. Postgres (R-9.2).

Detections live in blob storage; this database holds who may see what, plus the
site and device registries. Schema changes go through Alembic, never by hand.

*Was SQLite until Phase 1R (D-019).* "One file, small enough to copy around" was
the wrong trade on a container host, where the writable filesystem is ephemeral
and that file takes every account and device credential with it on the first
restart.

**Phase 1I adds `detection_events` here** (D-021, R-12): a *derived* index over
the event blobs, so a page of detections costs one query and zero storage reads.
Derived is the whole point — object storage stays the record, nothing writes to
that table but the indexer, and it must stay rebuildable from the container.
"""
from datetime import datetime, timezone
from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import SQLModel, Field, Column, DateTime, Index


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Postgres in production, SQLite in `make test`. JSONB is the right type on
# Postgres — binary, indexable — and does not exist on SQLite, so the variant
# keeps one model working on both rather than forking the schema.
_JSON_DOC = JSONB().with_variant(sa.JSON(), "sqlite")

# Every timestamp in this table is offset-aware and compared against other
# offset-aware values. Postgres needs telling; the naive/aware mismatch this
# avoids has already produced one unhandled 500 in the query path it replaces.
_TZ_DATETIME = DateTime(timezone=True)


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


class DetectionEvent(SQLModel, table=True):
    """A **derived** index over the event blobs (D-021, R-12.1).

    Object storage is the record. This table is a queryable copy of it, so a page
    of detections costs one query and zero storage reads. Three rules keep it
    honest and none of them is optional:

    - **Nothing writes here but the indexer** (R-12.2). No request path, no admin
      route, no migration data step. The moment a detection exists only here, this
      stops being an index and becomes a liability.
    - **It must stay rebuildable** from the container. Dropping the table costs a
      reconcile pass, never a detection.
    - **`event_id` is the natural key** and upserts are idempotent on it (R-12.3),
      which is what makes retries, duplicate pushes and overlapping reconcile
      passes safe by construction rather than by care.

    The full document is kept verbatim in `document` rather than being decomposed
    into columns. Two reasons: the API must return the event exactly as the device
    wrote it, including fields this version has never heard of (the same
    pass-through rule as the rollup routes), and a column set that has to grow
    every time the device adds a field is a schema migration coupled to someone
    else's release cycle. The columns beside it exist only because views filter
    and sort on them.
    """
    __tablename__ = "detection_event"
    __table_args__ = (
        # The one query this table exists to serve: a site's events, newest first.
        Index("ix_detection_event_site_captured", "site_id", "captured_utc"),
        # Drift is counted per site per day (R-12.5), which is this index read
        # rather than a table scan.
        Index("ix_detection_event_captured", "captured_utc"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    # Natural key. Unique because that is what makes the upsert idempotent —
    # the constraint is the mechanism, not a sanity check on top of one.
    event_id: str = Field(index=True, unique=True)

    site_id: str = Field(index=True)

    # Capture time, never upload time (R-8.4). Offset-aware, always: the contract
    # requires an offset on `captured_utc` and the upload endpoint rejects a naive
    # value at the boundary rather than letting it reach a comparison here.
    captured_utc: datetime = Field(sa_column=Column(_TZ_DATETIME, nullable=False))

    # Filter columns. Everything a view sorts or filters on, and nothing else.
    event_type: Optional[str] = Field(default=None, index=True)
    detector: Optional[str] = Field(default=None, index=True)
    score: Optional[float] = None            # nullable: every numeric field can be null
    suppressed: bool = False

    # The event exactly as the device wrote it. This is what the API returns.
    document: dict[str, Any] = Field(sa_column=Column(_JSON_DOC, nullable=False))

    # When we indexed it — not when it happened. This is the freshness half of
    # R-12.5: a page served from an index that stopped updating three days ago,
    # with no way for the caller to know, is the same class of lie as a device
    # reporting itself healthy while deaf.
    indexed_utc: datetime = Field(
        default_factory=_now,
        sa_column=Column(_TZ_DATETIME, nullable=False, default=_now))

    # 'push' or 'reconcile' — which path got here first.
    #
    # This is the drift metric for the push path specifically. If every row says
    # 'reconcile', the device push has silently stopped working and the only
    # symptom is latency, which nobody notices. Without this the answer to "is
    # the push actually delivering?" requires reading logs that may not exist.
    first_seen_via: str = Field(default="reconcile", index=True)


class DeviceConfig(SQLModel, table=True):
    """Tuned configuration per device (R-6.2). Absent row = defaults at version 1.

    `version` is an internal monotonic counter. It is **not** what the device
    compares: `admin._config_version()` turns it into the opaque date-stamped
    string that goes into the blob (`"2026-08-22-04"`), and the device re-applies
    when that string *differs* from the one in force, never when it increases
    (D-020). Do not reintroduce a "newer than" rule here — there is no ordering
    on that string and no expiry; a configuration stays in force until a
    different one verifies.

    `config_json` is stored already clamped, so what the panel shows, what gets
    signed and what status.json later reports are the same numbers.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    device_id: str = Field(index=True, unique=True)      # Device.device_id
    config_json: str
    version: int = 2                     # 1 is the implicit defaults version
    updated_utc: datetime = Field(default_factory=_now)
