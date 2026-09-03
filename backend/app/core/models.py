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


def as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Coerce a timestamp read back from the database to offset-aware UTC.

    **Use this on every datetime read off a row before comparing it to
    anything.** Postgres returns `timestamptz` columns offset-aware; SQLite has
    no timezone type and returns them naive, and the suite runs on SQLite while
    production runs on Postgres. Subtracting a naive value from an aware one
    raises `TypeError` rather than answering wrongly — so the failure appears
    only on the engine you are not looking at.

    This has now bitten three times: an unhandled 500 in the old storage-walking
    query path, the reconcile pass's day bucketing, and the silence check's
    renotify arithmetic. One helper, so there is no fourth.

    The stored value is UTC either way; only the tzinfo tag is missing.
    """
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


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

    # --- event push health (D-022) -------------------------------------------
    # The contract obliges us to surface a rejected push where `last_seen`
    # already is, rather than in a log. A device whose every POST has been
    # refused for a week — wrong site after a re-provision, a credential
    # revoked, a malformed document after a firmware change — otherwise looks
    # identical to a quiet one, and its events only appear at the next weekly
    # reconcile with nobody aware anything was wrong.
    #
    # Comparing these two timestamps is the whole diagnostic: an error stamp
    # newer than the success stamp means the push path is currently broken.
    last_push_utc: Optional[datetime] = Field(
        default=None, sa_column=Column(_TZ_DATETIME, nullable=True))
    last_push_error_utc: Optional[datetime] = Field(
        default=None, sa_column=Column(_TZ_DATETIME, nullable=True))
    last_push_error: Optional[str] = None


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


class DeviceAlert(SQLModel, table=True):
    """An open fault against a site, and what we have told anyone about it (R-7.5).

    Today there is one kind, `silent`: the unit has stopped reporting. R-7.4 is
    satisfied by a badge on a page, which is enough for a unit somebody is
    already looking at and useless for one that dies at 02:00 — and given the
    system exists to notice detonations, a silently dead node is the failure it
    is supposed to prevent.

    **This row is the anti-flood mechanism.** The check runs every few minutes;
    without somewhere to record that an alert is already open, every one of those
    passes would notify again. One row per outage: opened once, notified once,
    re-notified only on a slow cadence while it stays open, and closed when the
    unit comes back.
    """
    __tablename__ = "device_alert"

    id: Optional[int] = Field(default=None, primary_key=True)
    site_id: str = Field(index=True)
    kind: str = Field(default="silent", index=True)

    opened_utc: datetime = Field(
        default_factory=_now, sa_column=Column(_TZ_DATETIME, nullable=False))
    # The last heartbeat we saw before it went quiet — the "silent since" a human
    # actually wants, rather than when our check happened to notice.
    last_seen_utc: Optional[datetime] = Field(
        default=None, sa_column=Column(_TZ_DATETIME, nullable=True))
    # Null while open. Set when the unit reports again.
    cleared_utc: Optional[datetime] = Field(
        default=None, sa_column=Column(_TZ_DATETIME, nullable=True))

    # When we last sent something about this alert, and how many times. Null
    # notified_utc on an open alert means the notification itself failed — worth
    # seeing, because an alert raised and never delivered is the silent failure
    # this table exists to prevent.
    notified_utc: Optional[datetime] = Field(
        default=None, sa_column=Column(_TZ_DATETIME, nullable=True))
    notify_count: int = 0
    notify_error: Optional[str] = None

    @property
    def open(self) -> bool:
        return self.cleared_utc is None


class IndexerRun(SQLModel, table=True):
    """One reconcile pass over one site. The audit trail for R-12.5.

    Without this the reconcile is unfalsifiable: an index can look complete
    because it is complete, or because the pass has not run since Tuesday and
    nothing has arrived to contradict it. Those are indistinguishable from the
    outside, and the second one is how a dashboard ends up quietly
    under-reporting. So every pass records that it happened, what it found, and
    whether it failed.

    A row is written even when the pass raises, because "the reconcile has been
    crashing for a week" is precisely the thing that must not be invisible.
    """
    __tablename__ = "indexer_run"

    id: Optional[int] = Field(default=None, primary_key=True)
    site_id: str = Field(index=True)
    started_utc: datetime = Field(
        default_factory=_now,
        sa_column=Column(_TZ_DATETIME, nullable=False, index=True, default=_now))
    finished_utc: Optional[datetime] = Field(
        default=None, sa_column=Column(_TZ_DATETIME, nullable=True))

    # What the window covered, so a drift number can be read against the span it
    # describes rather than an assumed one.
    window_days: int = 0
    blobs_in_storage: int = 0
    newly_indexed: int = 0
    conflicting: int = 0
    rejected: int = 0
    drift: int = 0

    # Set when the pass raised. Non-null is a fault to surface, not a log line.
    error: Optional[str] = None

    # 'scheduled' or 'manual' — a drift number means something different when
    # somebody just pressed the button than when the timer has been running
    # unattended.
    trigger: str = "scheduled"

    @property
    def ok(self) -> bool:
        return self.error is None and self.drift == 0 and self.conflicting == 0


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
