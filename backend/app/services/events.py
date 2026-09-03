"""Reading detections out of blob storage, filtered and paginated (R-5.1, R-5.2).

SUPERSEDED BY D-021. This module is what Phase 1I replaces.

The docstring here used to claim that date-partitioned paths made a time range a
prefix listing "so no index and no database are needed (D-004)". The listing is
indeed cheap; what follows it is not. `list_events` issues one GET per blob the
listing returns, sequentially, filters in Python, and only then applies
`limit`/`offset` — so a page costs what the whole window costs, and `total`
requires reading everything. That satisfies R-5.1 while failing R-5.2, which is
why R-5.2 was restated as an outcome rather than a mechanism.

The filter predicate lives inside the blob body while the key encodes only the
day, so no amount of slicing earlier fixes it: you cannot tell whether a blob
matches without opening it. That is a data-model problem, and the answer is the
derived Postgres index (D-021, R-12), fed by the device push (D-022, R-6.3) and
kept correct by a reconcile pass over a trailing window (R-12.4).

Two defects in here are wrong at any volume and are tracked in PROGRESS.md under
Phase 1I: a naive (offset-less) `since` raises TypeError outside the guard below
and surfaces as a 500, and `_day_prefixes` derives partitions with `.date()` on a
possibly non-UTC offset, which drops a prefix at each boundary.
"""
from __future__ import annotations
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func
from sqlmodel import Session, col, select

from app.core.models import DetectionEvent, as_utc
from app.services.storage import Storage

SCHEMA_VERSION = 2


def _day_prefixes(site: str, start: date, end: date) -> list[str]:
    """Only the days asked for. This is R-5.2."""
    out, d = [], start
    while d <= end:
        out.append(f"sites/{site}/events/{d:%Y/%m/%d}/")
        d += timedelta(days=1)
    return out


def _as_utc(value: datetime) -> datetime:
    """Normalise a query bound to UTC.

    A caller may send `?since=2026-08-01T00:00:00` with no offset. The previous
    implementation compared that naive value against an offset-aware one, which
    raises `TypeError` in Python — outside its guard, so it surfaced as an
    unhandled 500 rather than an answer (R-5.6 says never a 500).

    A missing offset is read as UTC. That is a documented convention rather than
    a silent guess: every timestamp in this system is UTC, `captured_utc` is
    required to say so explicitly, and rejecting a convenience query parameter
    outright would break callers for no benefit. It is stated in
    `API-CONTRACT.md` so nobody has to infer it from behaviour.

    Same coercion as `models.as_utc`, kept as a named wrapper because the
    *reason* differs: that one repairs what SQLite hands back, this one applies a
    documented convention to caller input.
    """
    return as_utc(value)


def list_events(
    db: Session,
    site: str | list[str],
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    event_type: Optional[str] = None,
    min_score: float = 0.0,
    include_suppressed: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """A page of detections, from the index (D-021, R-12.1).

    One query, zero reads against object storage, at any window size. The
    envelope is unchanged from the storage-walking version this replaces, so the
    frontend cannot tell the difference — which was the point: the mechanism
    moved, the contract did not.

    `site` accepts a list as well as a string. The route passes one today, but
    cross-site queries are a thing the previous design could not express at all
    (R-12.7) and this is the whole cost of allowing them.
    """
    until = _as_utc(until or datetime.now(timezone.utc))
    since = _as_utc(since or (until - timedelta(days=7)))

    sites = [site] if isinstance(site, str) else list(site)

    conditions = [
        col(DetectionEvent.site_id).in_(sites),
        DetectionEvent.captured_utc >= since,
        DetectionEvent.captured_utc <= until,
    ]
    if event_type:
        conditions.append(DetectionEvent.event_type == event_type)
    if min_score:
        # A null score is an absence, not a zero, so it cannot satisfy a
        # minimum. Excluded rather than coerced (`score >= 0` would silently
        # admit every unscored event the moment a filter is applied).
        conditions.append(col(DetectionEvent.score) >= min_score)
    if not include_suppressed:
        conditions.append(col(DetectionEvent.suppressed).is_(False))

    total = db.exec(
        select(func.count()).select_from(DetectionEvent).where(*conditions)
    ).one()

    rows = db.exec(
        select(DetectionEvent)
        .where(*conditions)
        # `event_id` breaks ties. Without a total order, two events sharing a
        # `captured_utc` can swap places between requests, and offset pagination
        # then skips one and repeats another — a page that silently omits a
        # detection, which is the failure mode this whole subsystem is built to
        # avoid.
        .order_by(col(DetectionEvent.captured_utc).desc(),
                  col(DetectionEvent.event_id).desc())
        .offset(offset).limit(limit)
    ).all()

    items = []
    for row in rows:
        # The document is returned exactly as the device wrote it. The version
        # flag is added on the way out rather than stored, so the record in the
        # index stays byte-faithful to the blob (R-5.6, surfaced not swallowed).
        doc = dict(row.document)
        if doc.get("schema_version") != SCHEMA_VERSION:
            doc["_unknown_schema"] = True
        items.append(doc)

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < total,
        # `index_updated_utc` replaces `scanned_blobs` (D-021, D-022).
        #
        # A scan count served from an index describes no work at all, and would
        # keep returning a plausible number forever. What a caller actually needs
        # to know is whether the answer is current: a page served from an index
        # that stopped updating three days ago, with no way to tell, is the same
        # class of lie as a device reporting itself healthy while deaf.
        "index_updated_utc": _index_updated(db, sites),
    }


def _index_updated(db: Session, sites: list[str]) -> Optional[str]:
    """When the index last took anything in for these sites.

    `None` means nothing has ever been indexed — a fresh deployment, or an
    indexer that has never run. Both are worth showing rather than hiding behind
    an empty list of events, because "no detections" and "no data reaching us"
    look identical to a reader and mean opposite things.
    """
    newest = db.exec(
        select(func.max(DetectionEvent.indexed_utc))
        .where(col(DetectionEvent.site_id).in_(sites))
    ).one()
    newest = as_utc(newest)
    return newest.isoformat() if newest else None


def read_json(storage: Storage, path: str) -> Optional[dict]:
    """Single rollup blob. Returns None rather than raising, so one missing file
    never takes the rest of the dashboard down (R-7.3)."""
    try:
        return json.loads(storage.get(path))
    except Exception:
        return None


def read_json_with_etag(storage: Storage, path: str) -> tuple[Optional[dict], Optional[str]]:
    """As `read_json`, plus a strong ETag over the exact bytes in storage (R-5.7).

    Hashing the bytes rather than the parsed document is deliberate: it is what
    actually changed, it costs nothing extra, and it cannot be fooled by two
    different serialisations of the same values.
    """
    try:
        raw = storage.get(path)
    except Exception:
        return None, None
    try:
        doc = json.loads(raw)
    except Exception:
        # Malformed is not missing. The caller still reports it as unavailable,
        # but an ETag on unparseable bytes would be a lie about what we served.
        return None, None
    return doc, '"' + hashlib.sha256(raw).hexdigest()[:32] + '"' 
