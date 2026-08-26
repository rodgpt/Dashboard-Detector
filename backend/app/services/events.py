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

from app.services.storage import Storage

SCHEMA_VERSION = 2


def _day_prefixes(site: str, start: date, end: date) -> list[str]:
    """Only the days asked for. This is R-5.2."""
    out, d = [], start
    while d <= end:
        out.append(f"sites/{site}/events/{d:%Y/%m/%d}/")
        d += timedelta(days=1)
    return out


def list_events(
    storage: Storage,
    site: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    event_type: Optional[str] = None,
    min_score: float = 0.0,
    include_suppressed: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> dict:

    until = until or datetime.now(timezone.utc)
    since = since or (until - timedelta(days=7))

    names: list[str] = []
    for pfx in _day_prefixes(site, since.date(), until.date()):
        names.extend(n for n in storage.list(pfx) if n.endswith(".json"))
    names.sort(reverse=True)                      # newest first; paths sort chronologically

    matched, scanned = [], 0
    for name in names:
        scanned += 1
        try:
            ev = json.loads(storage.get(name))
        except Exception:
            continue                              # a malformed blob must not take the page down (R-5.6)
        if ev.get("schema_version") != SCHEMA_VERSION:
            ev["_unknown_schema"] = True          # surfaced, not swallowed
        try:
            captured = datetime.fromisoformat(ev["captured_utc"])
        except Exception:
            continue
        if not (since <= captured <= until):
            continue
        if event_type and ev.get("event_type") != event_type:
            continue
        if (ev.get("score") or 0) < min_score:
            continue
        if not include_suppressed and ev.get("suppressed"):
            continue
        matched.append(ev)

    page = matched[offset:offset + limit]
    return {
        "items": page,
        "total": len(matched),
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(page) < len(matched),
        "scanned_blobs": scanned,                 # visible cost, so nobody has to guess
    }


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
