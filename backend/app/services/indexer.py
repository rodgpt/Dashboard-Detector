"""Writing event documents into the derived index (D-021, D-022, R-12).

**This module is the only thing that writes `detection_event`** (R-12.2). Two
callers reach it and they are not alternatives:

- `POST /api/devices/events` — the device pushing an event as it happens. Fast,
  allowed to fail, carries nothing the blob does not (R-6.3).
- the reconcile pass — reading a trailing window of blob prefixes and indexing
  whatever the push did not deliver. Slow, periodic, and the reason the system
  is correct (R-12.4).

Both call `index_event`. That is deliberate: idempotency is the property the
whole design rests on, and it is only trustworthy if there is exactly one place
it can be got wrong.

**Idempotency is enforced by the unique constraint on `event_id`, not by a
check-then-insert.** A `SELECT` followed by an `INSERT` looks equivalent and is
not: two pushes of the same event arriving together both see nothing, both
insert, and one of them fails at the database anyway — or worse, on an engine
without the constraint, both succeed and the event is double-counted. So the
insert is attempted, and a violation *is* the answer: already indexed. The
constraint is the mechanism (R-12.3).

The attempt runs inside a SAVEPOINT so that a conflict rolls back one row rather
than poisoning the surrounding transaction. That matters for the reconcile pass,
which indexes many events under one session and must not lose a batch because
the third item was already present — which, in steady state, all of them are.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.core.models import DetectionEvent

# Where an event came from first. Not where it came from most recently: once a
# row exists nothing overwrites it, so this records which path actually won.
VIA_PUSH = "push"
VIA_RECONCILE = "reconcile"


class EventRejected(ValueError):
    """The document cannot be indexed and re-sending it unchanged will not help.

    Distinct from "already indexed", which is success. This is a `400` on the
    push route and a counted, surfaced skip in the reconcile pass — never a
    silent drop, because an event the device believes it delivered and we
    believe we rejected is exactly the gap this system exists to close.
    """


def _require_aware(value: Any, field: str) -> datetime:
    """Parse a contract timestamp, refusing a naive one.

    `captured_utc` MUST carry a UTC offset — see **Event upload** in
    `DATA-CONTRACT.md`. Two failures follow from a naive value and neither is
    visible at the time it happens. It cannot be compared against an
    offset-aware value (Python raises rather than answering wrongly, which is
    how this reached an unhandled 500 in the query path this index replaces),
    and the date partition is derived from it, so the event files under the
    wrong day where a trailing-window read will not find it.

    Rejecting at the boundary turns both into one loud error at upload time.
    """
    if not isinstance(value, str) or not value:
        raise EventRejected(f"{field} is required and must be an ISO 8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise EventRejected(f"{field} is not a valid ISO 8601 timestamp: {value!r}")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EventRejected(
            f"{field} must carry a UTC offset (got {value!r}). "
            "A naive timestamp is ambiguous and partitions to the wrong day")
    return parsed


def _require_str(doc: dict, field: str) -> str:
    value = doc.get(field)
    if not isinstance(value, str) or not value:
        raise EventRejected(f"{field} is required and must be a non-empty string")
    return value


def _optional_float(value: Any, field: str) -> Optional[float]:
    """`None` stays `None`. Every numeric field in the contract may be null, and
    null means absent — never zero. A zero score is a reading; a null is silence
    about the score."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EventRejected(f"{field} must be a number or null (got {value!r})")
    return float(value)


def to_row(doc: dict, *, via: str) -> DetectionEvent:
    """Build the index row from an event document, validating what we index on.

    Only the fields the index filters and sorts on are validated. Everything else
    passes through untouched inside `document`, including fields this version has
    never heard of — the same pass-through rule the rollup routes follow. A field
    the device adds must reach the browser and be surfaced, not be eaten here on
    the way in.
    """
    if not isinstance(doc, dict):
        raise EventRejected("event must be a JSON object")

    event_id = _require_str(doc, "event_id")
    site_id = _require_str(doc, "site")
    captured = _require_aware(doc.get("captured_utc"), "captured_utc")

    event_type = doc.get("event_type")
    if event_type is not None and not isinstance(event_type, str):
        raise EventRejected("event_type must be a string or absent")

    detector = doc.get("detector")
    if detector is not None and not isinstance(detector, str):
        raise EventRejected("detector must be a string or absent")

    return DetectionEvent(
        event_id=event_id,
        site_id=site_id,
        captured_utc=captured,
        event_type=event_type,
        detector=detector,
        score=_optional_float(doc.get("score"), "score"),
        # Absent means not suppressed. The contract's default, not a guess:
        # a suppressed event always carries the flag (D-008).
        suppressed=bool(doc.get("suppressed", False)),
        document=doc,
        first_seen_via=via,
    )


def index_event(db: Session, doc: dict, *, via: str) -> bool:
    """Index one event. Returns True if it was new, False if already present.

    **False is success, not failure.** A duplicate is the expected case: the
    reconcile pass re-reads prefixes it has already read, and an event the device
    pushed will be seen again by the next pass. Callers that treat a re-index as
    an error have reintroduced the fragility the unique constraint removes — the
    push route returns `202` either way, and never `409`.

    Raises `EventRejected` if the document cannot be indexed at all.
    """
    row = to_row(doc, via=via)
    try:
        # SAVEPOINT: a unique violation rolls back this row only. Without it the
        # surrounding transaction aborts and a reconcile batch dies on its first
        # already-present event, which is every event in steady state.
        with db.begin_nested():
            db.add(row)
            db.flush()
        return True
    except IntegrityError:
        # The only unique constraint on this table is `event_id`, so this is
        # unambiguous: someone got here first. That someone may be the other
        # ingestion path, running concurrently, which is precisely the race the
        # constraint exists to settle.
        return False
