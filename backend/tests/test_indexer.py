"""The indexer's failure modes, which are the ones that under-report silently.

Every test here corresponds to a way the index could end up disagreeing with
storage while looking perfectly healthy — the same shape as a device reporting
itself healthy while deaf, and the reason R-12.3 and R-12.5 exist.
"""
import os, tempfile

# `setdefault`, not `update`. `settings()` is lru_cached and the whole suite
# shares one process, so whichever test module imports first establishes the
# environment for all of them. Overwriting it here pointed the storage root at
# an empty directory and took seven unrelated tests down with it.
for _k, _v in {
    "OCEANKIND_SESSION_SECRET": "x" * 40,
    "OCEANKIND_STORAGE_BACKEND": "local",
    "OCEANKIND_LOCAL_STORAGE_ROOT": tempfile.mkdtemp(),
    "OCEANKIND_DB_URL": f"sqlite:///{tempfile.mktemp()}",
    "OCEANKIND_COOKIE_SECURE": "false",
    "OCEANKIND_CONFIG_HMAC_KEY": "test-signing-key-0123456789abcdef",
}.items():
    os.environ.setdefault(_k, _v)

import copy
import pytest
from sqlmodel import Session, SQLModel, select

from app.core.database import engine
from app.core.models import DetectionEvent
from app.services.indexer import (
    EventRejected, VIA_PUSH, VIA_RECONCILE, index_event, to_row,
)


# A real v2 event, in the shape `tools/generate_fixtures.py` writes and the
# device emits. Copied rather than invented, so a contract change breaks these
# tests instead of leaving them passing against a shape nothing produces.
EVENT = {
    "schema_version": 2,
    "site": "matanzas",
    "device": "Rpi_matanzas",
    "generated_utc": "2026-07-27T23:29:31.747486+00:00",
    "event_id": "929d674d-798e-475f-afb5-6207ddecc40b",
    "captured_utc": "2026-07-27T23:29:31.747486+00:00",
    "uploaded_utc": "2026-07-27T23:29:44.701518+00:00",
    "event_type": "blast",
    "detector": "ml_mfcc",
    "score": 0.8128,
    "suppressed": False,
    "audio_level": 0.0291,
    "peak_db": -11.3,
    "bearing_deg": None,
    "clip": {
        "path": "sites/matanzas/clips/2026/07/27/929d674d-798e-475f-afb5-6207ddecc40b.wav",
        "sample_rate": 48000, "channels": 2, "duration_s": 5.0, "uploaded": True,
    },
    "detector_meta": {},
}


def ev(**overrides):
    """A copy of the canonical event with fields replaced or removed.

    `None` as a value in `overrides` deletes the key, so "absent" and
    "explicitly null" can be tested apart — the contract treats them
    differently and so must we.
    """
    doc = copy.deepcopy(EVENT)
    for k, v in overrides.items():
        if v is _ABSENT:
            doc.pop(k, None)
        else:
            doc[k] = v
    return doc


class _Absent:
    pass


_ABSENT = _Absent()


@pytest.fixture()
def db():
    SQLModel.metadata.create_all(engine())
    with Session(engine()) as s:
        for row in s.exec(select(DetectionEvent)).all():
            s.delete(row)
        s.commit()
        yield s


# --- idempotency: the property everything else rests on (R-12.3) -------------

def test_indexing_the_same_event_twice_produces_one_row(db):
    assert index_event(db, EVENT, via=VIA_RECONCILE) is True
    assert index_event(db, EVENT, via=VIA_RECONCILE) is False
    db.commit()
    assert len(db.exec(select(DetectionEvent)).all()) == 1


def test_push_then_reconcile_produces_one_row(db):
    """The normal steady state: the device pushed it, then the weekly pass reads
    the same blob. This must be a no-op, not a duplicate and not an error."""
    assert index_event(db, EVENT, via=VIA_PUSH) is True
    assert index_event(db, EVENT, via=VIA_RECONCILE) is False
    db.commit()
    rows = db.exec(select(DetectionEvent)).all()
    assert len(rows) == 1
    # first_seen_via records which path actually won, and is not overwritten by
    # the later one. If this ever reads 'reconcile' across the board in
    # production, the push has silently stopped working.
    assert rows[0].first_seen_via == VIA_PUSH


def test_a_conflict_does_not_poison_the_batch(db):
    """The reconcile pass indexes many events under one session, and in steady
    state nearly all of them are already present. A duplicate must roll back one
    row, not abort the transaction and lose the genuinely new events after it."""
    index_event(db, EVENT, via=VIA_RECONCILE)
    db.commit()

    fresh = ev(event_id="11111111-1111-4111-8111-111111111111")
    later = ev(event_id="22222222-2222-4222-8222-222222222222")

    assert index_event(db, EVENT, via=VIA_RECONCILE) is False   # duplicate
    assert index_event(db, fresh, via=VIA_RECONCILE) is True    # must still work
    assert index_event(db, later, via=VIA_RECONCILE) is True
    db.commit()
    assert len(db.exec(select(DetectionEvent)).all()) == 3


# --- the timestamp rule (DATA-CONTRACT: Event upload) ------------------------

def test_naive_captured_utc_is_rejected(db):
    """A naive timestamp is ambiguous, cannot be compared against an aware one,
    and partitions to the wrong day. Rejected loudly at the boundary rather than
    surfacing as a 500 three weeks later in a query."""
    with pytest.raises(EventRejected, match="UTC offset"):
        index_event(db, ev(captured_utc="2026-07-27T23:29:31.747486"), via=VIA_PUSH)


def test_non_utc_offset_is_accepted_and_refers_to_the_right_instant():
    """An offset is what the contract requires, not specifically `+00:00`. Chile
    time is unambiguous and must be accepted — and must mean the same instant as
    the equivalent Z value, since the day-boundary bug this closes came from
    treating a local-time value as if it were UTC.

    Asserted on `to_row` rather than a stored row on purpose: SQLite has no
    native timezone type, so a round-trip there tests SQLAlchemy's dialect
    behaviour rather than this module's parsing. Production is Postgres
    `timestamptz`, which normalises to UTC on the way in.
    """
    chile = to_row(ev(captured_utc="2026-07-27T20:29:31.747486-03:00"), via=VIA_PUSH)
    utc = to_row(EVENT, via=VIA_PUSH)
    assert chile.captured_utc.utcoffset() is not None
    assert chile.captured_utc == utc.captured_utc      # 20:29-03:00 == 23:29Z


def test_garbage_timestamp_is_rejected_not_swallowed(db):
    with pytest.raises(EventRejected):
        index_event(db, ev(captured_utc="last tuesday"), via=VIA_PUSH)


# --- what must be present, and what must survive untouched -------------------

@pytest.mark.parametrize("field", ["event_id", "site", "captured_utc"])
def test_missing_required_field_is_rejected(db, field):
    with pytest.raises(EventRejected, match=field):
        index_event(db, ev(**{field: _ABSENT}), via=VIA_PUSH)


def test_unknown_fields_survive_into_the_document(db):
    """A field the device adds must reach the browser, not be eaten on the way
    in. This is the same pass-through rule the rollup routes follow, and the
    reason the whole document is stored rather than decomposed into columns."""
    index_event(db, ev(brand_new_field={"nested": [1, 2, 3]}), via=VIA_PUSH)
    db.commit()
    row = db.exec(select(DetectionEvent)).one()
    assert row.document["brand_new_field"] == {"nested": [1, 2, 3]}
    # and nothing was dropped
    assert row.document["detector_meta"] == {}
    assert row.document["clip"]["uploaded"] is True


def test_null_score_stays_null(db):
    """Every numeric field can be null and null means absent, never zero. A zero
    score is a reading; a null is silence about the score."""
    index_event(db, ev(score=None), via=VIA_PUSH)
    db.commit()
    assert db.exec(select(DetectionEvent)).one().score is None


def test_suppressed_event_is_indexed_like_any_other(db):
    """Suppressed means the notification was withheld, not that the detection
    was less real (D-008, R-8.2). It is indexed, flagged, and never dropped."""
    index_event(db, ev(suppressed=True), via=VIA_PUSH)
    db.commit()
    assert db.exec(select(DetectionEvent)).one().suppressed is True


def test_unknown_schema_version_is_indexed_not_refused(db):
    """Surfaced, not swallowed — and not refused either. Refusing would lose the
    event entirely; the read path flags the mismatch so it degrades visibly
    (R-5.6)."""
    index_event(db, ev(schema_version=99), via=VIA_PUSH)
    db.commit()
    assert db.exec(select(DetectionEvent)).one().document["schema_version"] == 99


def test_filter_columns_are_extracted_for_querying(db):
    row = to_row(EVENT, via=VIA_PUSH)
    assert (row.event_id, row.site_id, row.event_type, row.detector) == (
        EVENT["event_id"], "matanzas", "blast", "ml_mfcc")
    assert row.score == pytest.approx(0.8128)
