"""Reading detections out of blob storage, filtered and paginated (R-5.1, R-5.2).

This is what stops the browser downloading everything. The date-partitioned path
layout means a time range is a prefix listing rather than a scan, so no index and
no database are needed (D-004).
"""
from __future__ import annotations
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
