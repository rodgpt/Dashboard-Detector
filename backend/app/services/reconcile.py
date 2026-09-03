"""The reconcile pass, and the drift metric (R-12.4, R-12.5, D-021, D-022).

**This is the correctness mechanism.** The device push is an optimisation and is
allowed to fail; this pass is what makes the index complete regardless. Anything
that makes correctness depend on the push instead has broken the design.

Why a trailing window rather than a high-water mark
---------------------------------------------------
Event partitions are keyed on `captured_utc`, not on arrival. A device that loses
its link spools locally and drains when it returns, so an event captured on the
Tuesday can appear in Tuesday's prefix on the Friday — in a directory a consumer
has already read to the end of.

A mark ("indexed up to day N") therefore fails in a way nothing detects: it
advances on the newest thing seen, while late data arrives *behind* it. Once the
mark passes a partition, anything landing there afterwards is unreachable,
permanently and silently. So the pass re-examines a window of days wide enough to
cover the longest outage the system intends to survive.

Why re-reading a fortnight of prefixes is nearly free
-----------------------------------------------------
`{event_id}` is in the blob name — `{ISO8601}_{uuid4}.json` — so the pass can
tell what is new *without opening anything*:

1. list the prefixes in the window (names only, no blob fetched)
2. one query for the `event_id`s already indexed in that range
3. set difference
4. fetch only the blobs in the difference

In steady state the difference is empty and the pass costs a handful of list
calls and one query. That is what makes a generous window affordable, and it is
why the window should be chosen from how long a device might be offline rather
than from what feels cheap.

**Nothing here ever opens a clip.** Everything indexed lives in the event JSON,
which is ~600 bytes against ~960 KB of WAV. A reconcile that touched audio would
be three orders of magnitude more expensive than one that does not.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlmodel import Session, select

from app.core.models import DetectionEvent, as_utc
from app.services.indexer import EventRejected, VIA_RECONCILE, index_event
from app.services.storage import Storage

log = logging.getLogger(__name__)

# At least as long as the longest device outage we intend to survive (R-12.4).
# This is a commitment, not a tuning knob: "we will not lose events from a unit
# that was offline for less than this". Raising it costs list calls; lowering it
# costs events, silently.
DEFAULT_WINDOW_DAYS = 14

EVENTS_PREFIX = "sites/{site_id}/events/{day:%Y/%m/%d}/"


@dataclass
class DayStat:
    """One day-partition of one site, before and after the pass."""
    day: date
    blobs_in_storage: int = 0
    already_indexed: int = 0
    fetched: int = 0
    newly_indexed: int = 0
    rejected: int = 0
    conflicting: int = 0

    @property
    def drift(self) -> int:
        """Blobs in storage with no row of their own in the index (R-12.5).

        Non-zero is a fault, not a statistic. It means events exist in the record
        that the dashboard will not show, which is the same failure as a device
        reporting itself healthy while deaf — and the reason this number is
        surfaced rather than logged.

        `conflicting` blobs count as drift deliberately. They are blobs whose
        content was never indexed, so the index does not represent them, and
        calling them covered because *something* holds their `event_id` would be
        the index lying about its own completeness.
        """
        return self.blobs_in_storage - (self.already_indexed + self.newly_indexed)


@dataclass
class ReconcileResult:
    site_id: str
    since: date
    until: date
    days: list[DayStat] = field(default_factory=list)
    # Blob names that could not be indexed. Counted and surfaced, never dropped:
    # a malformed event must not stall the pass, and must not vanish either.
    rejections: list[tuple[str, str]] = field(default_factory=list)

    @property
    def blobs_in_storage(self) -> int:
        return sum(d.blobs_in_storage for d in self.days)

    @property
    def newly_indexed(self) -> int:
        return sum(d.newly_indexed for d in self.days)

    @property
    def fetched(self) -> int:
        return sum(d.fetched for d in self.days)

    @property
    def drift(self) -> int:
        return sum(d.drift for d in self.days)

    @property
    def conflicting(self) -> int:
        return sum(d.conflicting for d in self.days)

    @property
    def days_with_drift(self) -> list[DayStat]:
        return [d for d in self.days if d.drift != 0]

    @property
    def healthy(self) -> bool:
        return self.drift == 0 and not self.rejections


def _utc_date(value: datetime) -> date:
    """The partition a timestamp belongs to.

    Normalised to UTC first, deliberately. Partitions are derived from
    `captured_utc` in UTC, so taking `.date()` off a value carrying a non-UTC
    offset picks the *local* date and silently addresses the wrong prefix — a
    bug that already exists in the storage-reading query path this index
    replaces, and which is not being carried forward.
    """
    return value.astimezone(timezone.utc).date()


def _window(days: int, now: Optional[datetime] = None) -> tuple[date, date]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    until = now.date()
    return until - timedelta(days=days - 1), until


def _day_range(since: date, until: date) -> Iterable[date]:
    day = since
    while day <= until:
        yield day
        day += timedelta(days=1)


def event_id_from_name(name: str) -> Optional[str]:
    """Pull `event_id` out of a blob name without opening it.

    Names are `{YYYY-MM-DDTHH-MM-SS}_{uuid4}.json` and the uuid is the
    `event_id`, which is what lets the pass diff storage against the index for
    the price of a listing.

    Returns None when the name does not match. **The caller must then fetch the
    blob rather than skip it** — a file we cannot name-parse is exactly the kind
    of thing that must not be assumed already indexed. Guessing "probably fine"
    here would reintroduce silent under-reporting through the back door.
    """
    stem = name.rsplit("/", 1)[-1]
    if not stem.endswith(".json"):
        return None
    stem = stem[: -len(".json")]
    _, sep, candidate = stem.partition("_")
    if not sep or not candidate:
        return None
    return candidate


def _indexed_ids_by_day(db: Session, site_id: str, since: date,
                        until: date) -> dict[date, set[str]]:
    """`event_id`s already indexed, bucketed by the partition they belong to.

    Bucketed in Python rather than with a SQL `date_trunc`: the suite runs on
    SQLite and production on Postgres, and the two spell date extraction
    differently. Two columns over a fortnight is a few thousand rows, so the
    portability is free.
    """
    start = datetime.combine(since, datetime.min.time(), tzinfo=timezone.utc)
    end = datetime.combine(until + timedelta(days=1), datetime.min.time(),
                           tzinfo=timezone.utc)
    rows = db.exec(
        select(DetectionEvent.event_id, DetectionEvent.captured_utc)
        .where(DetectionEvent.site_id == site_id)
        .where(DetectionEvent.captured_utc >= start)
        .where(DetectionEvent.captured_utc < end)
    ).all()

    out: dict[date, set[str]] = {}
    for event_id, captured in rows:
        out.setdefault(_utc_date(as_utc(captured)), set()).add(event_id)
    return out


def reconcile_site(db: Session, storage: Storage, site_id: str, *,
                   days: int = DEFAULT_WINDOW_DAYS,
                   now: Optional[datetime] = None) -> ReconcileResult:
    """Index anything in the trailing window that is not in the index yet.

    Idempotent and safe to overlap with itself and with the push route: every
    write goes through `index_event`, which settles conflicts on the unique
    constraint (R-12.3).
    """
    since, until = _window(days, now)
    result = ReconcileResult(site_id=site_id, since=since, until=until)
    indexed = _indexed_ids_by_day(db, site_id, since, until)

    for day in _day_range(since, until):
        stat = DayStat(day=day)
        known = indexed.get(day, set())
        prefix = EVENTS_PREFIX.format(site_id=site_id, day=day)

        # Names only. No blob is opened here, and `.wav` is never listed because
        # clips live under a parallel `clips/` tree.
        names = [n for n in storage.list(prefix) if n.endswith(".json")]
        stat.blobs_in_storage = len(names)

        for name in names:
            event_id = event_id_from_name(name)
            if event_id is not None and event_id in known:
                stat.already_indexed += 1
                continue

            # Either genuinely new, or a name we could not parse. Both get
            # fetched: never assume an unparseable name is already covered.
            try:
                raw = storage.get(name)
            except Exception as e:                     # noqa: BLE001
                # Unreadable now does not mean absent forever. Counted as drift
                # so it stays visible, and retried on the next pass.
                log.warning("reconcile: could not read %s: %s", name, e)
                result.rejections.append((name, f"unreadable: {e}"))
                continue

            stat.fetched += 1
            try:
                import json
                doc = json.loads(raw)
            except Exception as e:                     # noqa: BLE001
                stat.rejected += 1
                result.rejections.append((name, f"not valid JSON: {e}"))
                continue

            try:
                if index_event(db, doc, via=VIA_RECONCILE):
                    stat.newly_indexed += 1
                elif event_id is None:
                    # Name was unparseable, so the diff could not rule it out;
                    # the row turns out to exist. Ordinary, and covered.
                    stat.already_indexed += 1
                else:
                    # The name-diff said this `event_id` was NOT in the index for
                    # this day, yet the insert conflicted. So a row holds that id
                    # and this blob is not what produced it: two distinct blobs
                    # claiming one `event_id`.
                    #
                    # Not absorbed as "already indexed". This blob's content was
                    # never indexed and never will be, so counting it as covered
                    # would make the pass report healthy over a tree it is
                    # silently under-representing — the exact failure R-12.5
                    # exists to catch. It stays drift, and it is named.
                    stat.conflicting += 1
                    result.rejections.append((
                        name, f"event_id {event_id} is already held by a different "
                              "document; this blob's content is not in the index"))
            except EventRejected as e:
                # A malformed event must not stall the pass and must not vanish
                # from view either (R-12.5).
                stat.rejected += 1
                result.rejections.append((name, str(e)))

        result.days.append(stat)

    db.commit()

    if not result.healthy:
        log.warning(
            "reconcile %s: drift=%d rejected=%d over %s..%s",
            site_id, result.drift, len(result.rejections), since, until)
    return result


def reconcile(db: Session, storage: Storage, site_ids: Iterable[str], *,
              days: int = DEFAULT_WINDOW_DAYS,
              now: Optional[datetime] = None) -> dict[str, ReconcileResult]:
    """Run the pass across sites. One site failing must not stop the others."""
    out: dict[str, ReconcileResult] = {}
    for site_id in site_ids:
        try:
            out[site_id] = reconcile_site(db, storage, site_id, days=days, now=now)
        except Exception:                              # noqa: BLE001
            # A site whose storage is unreachable is a fault to surface, not a
            # reason to leave every other site unreconciled.
            log.exception("reconcile: site %s failed", site_id)
            db.rollback()
    return out


def measure_drift(db: Session, storage: Storage, site_id: str, *,
                  days: int = DEFAULT_WINDOW_DAYS,
                  now: Optional[datetime] = None) -> ReconcileResult:
    """Count blobs against rows, per day, **without writing anything** (R-12.5).

    This is the metric the admin panel reads. It opens no blob and indexes
    nothing: listing names is enough to count them, and the index is one query.
    Cheap enough to run on demand, which is the point — a drift number nobody can
    ask for is a drift number nobody looks at.
    """
    since, until = _window(days, now)
    result = ReconcileResult(site_id=site_id, since=since, until=until)
    indexed = _indexed_ids_by_day(db, site_id, since, until)

    for day in _day_range(since, until):
        prefix = EVENTS_PREFIX.format(site_id=site_id, day=day)
        names = [n for n in storage.list(prefix) if n.endswith(".json")]
        known = indexed.get(day, set())
        stat = DayStat(day=day, blobs_in_storage=len(names))
        # A name we cannot parse counts as not-indexed. Erring towards reporting
        # drift that is not there beats hiding drift that is.
        stat.already_indexed = sum(
            1 for n in names
            if (eid := event_id_from_name(n)) is not None and eid in known)
        result.days.append(stat)
    return result
