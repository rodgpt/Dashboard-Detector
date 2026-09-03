"""`list_events` served from the index (R-12.1, R-5.1, R-5.2, D-021).

The envelope is unchanged from the storage-walking version this replaces — the
mechanism moved, the contract did not — so most of these assert that the answers
are the same while the cost is not.
"""
import os, tempfile

for _k, _v in {
    "OCEANKIND_SESSION_SECRET": "x" * 40,
    "OCEANKIND_STORAGE_BACKEND": "local",
    "OCEANKIND_LOCAL_STORAGE_ROOT": tempfile.mkdtemp(),
    "OCEANKIND_DB_URL": f"sqlite:///{tempfile.mktemp()}",
    "OCEANKIND_COOKIE_SECURE": "false",
    "OCEANKIND_CONFIG_HMAC_KEY": "test-signing-key-0123456789abcdef",
}.items():
    os.environ.setdefault(_k, _v)

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, SQLModel, select

from app.core.database import engine
from app.core.models import DetectionEvent
from app.services.events import list_events
from app.services.indexer import index_event, VIA_PUSH

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)


def make(captured, event_id, **over):
    return {
        "schema_version": 2, "site": "matanzas", "device": "Rpi_matanzas",
        "event_id": event_id, "captured_utc": captured.isoformat(),
        "event_type": "vessel", "detector": "psd_tonal", "score": 0.7,
        "suppressed": False, **over,
    }


@pytest.fixture()
def db():
    SQLModel.metadata.create_all(engine())
    with Session(engine()) as s:
        for row in s.exec(select(DetectionEvent)).all():
            s.delete(row)
        s.commit()
        yield s


@pytest.fixture()
def seeded(db):
    """Twelve events over twelve hours, with the awkward cases mixed in."""
    for i in range(12):
        index_event(db, make(
            NOW - timedelta(hours=i), f"e{i:02d}-0000-4000-8000-0000000000{i:02d}",
            event_type="blast" if i % 3 == 0 else "vessel",
            score=None if i == 5 else round(0.5 + i * 0.04, 2),
            suppressed=(i % 4 == 0),
        ), via=VIA_PUSH)
    db.commit()
    return db


# --- the acceptance criterion for R-12.1 ------------------------------------

def test_a_page_costs_zero_storage_reads(seeded, monkeypatch):
    """*A page of events, filtered and sorted, is served with zero reads against
    object storage.* Asserted by making any storage access explode: if the query
    path still touches a blob, this fails loudly rather than quietly costing a
    thousand round trips in production, which is exactly how the original defect
    survived — `LocalStorage` made those reads instant."""
    import app.services.storage as storage_mod

    def explode(*a, **k):
        raise AssertionError("list_events touched object storage")

    monkeypatch.setattr(storage_mod.LocalStorage, "get", explode)
    monkeypatch.setattr(storage_mod.LocalStorage, "list", explode)

    page = list_events(seeded, "matanzas", since=NOW - timedelta(days=7), until=NOW)
    assert page["total"] == 12 and len(page["items"]) == 12


# --- the envelope, unchanged -------------------------------------------------

def test_envelope_shape(seeded):
    page = list_events(seeded, "matanzas", since=NOW - timedelta(days=7), until=NOW, limit=5)
    assert set(page) == {"items", "total", "limit", "offset",
                         "has_more", "index_updated_utc"}
    assert page["total"] == 12 and page["limit"] == 5 and page["has_more"] is True
    assert len(page["items"]) == 5


def test_items_are_the_device_document_untouched(seeded):
    page = list_events(seeded, "matanzas", since=NOW - timedelta(days=7), until=NOW, limit=1)
    doc = page["items"][0]
    assert doc["device"] == "Rpi_matanzas" and doc["schema_version"] == 2
    assert "_unknown_schema" not in doc


def test_unknown_schema_version_is_flagged_on_the_way_out(db):
    index_event(db, make(NOW, "odd-0000-4000-8000-000000000099", schema_version=99), via=VIA_PUSH)
    db.commit()
    page = list_events(db, "matanzas", since=NOW - timedelta(days=1), until=NOW)
    assert page["items"][0]["_unknown_schema"] is True
    # ...but the stored copy stays byte-faithful to the blob
    assert db.exec(select(DetectionEvent)).one().document.get("_unknown_schema") is None


# --- ordering and pagination -------------------------------------------------

def test_newest_first(seeded):
    page = list_events(seeded, "matanzas", since=NOW - timedelta(days=7), until=NOW)
    stamps = [i["captured_utc"] for i in page["items"]]
    assert stamps == sorted(stamps, reverse=True)


def test_pagination_is_stable_across_ties(db):
    """Events sharing a `captured_utc` must still have a total order, or offset
    pagination skips one row and repeats another — a page that silently omits a
    detection."""
    for i in range(10):
        index_event(db, make(NOW, f"tie{i}-0000-4000-8000-00000000000{i}"), via=VIA_PUSH)
    db.commit()

    seen, offset = [], 0
    while True:
        page = list_events(db, "matanzas", since=NOW - timedelta(days=1),
                           until=NOW, limit=3, offset=offset)
        seen += [i["event_id"] for i in page["items"]]
        if not page["has_more"]:
            break
        offset += 3
    assert len(seen) == 10 and len(set(seen)) == 10, "paging skipped or repeated a row"


def test_paging_never_returns_more_than_the_limit(seeded):
    """R-5.1: 50 requested returns 50 regardless of how many exist."""
    page = list_events(seeded, "matanzas", since=NOW - timedelta(days=7), until=NOW, limit=2)
    assert len(page["items"]) == 2 and page["total"] == 12


# --- filters -----------------------------------------------------------------

def test_filter_by_type(seeded):
    page = list_events(seeded, "matanzas", since=NOW - timedelta(days=7),
                       until=NOW, event_type="blast")
    assert page["total"] == 4
    assert {i["event_type"] for i in page["items"]} == {"blast"}


def test_excluding_suppressed_is_possible_but_not_the_default(seeded):
    """Suppressed events are shown by default: a cooldown withholds a
    notification, it does not make the detection less real (R-8.2, D-008)."""
    default = list_events(seeded, "matanzas", since=NOW - timedelta(days=7), until=NOW)
    without = list_events(seeded, "matanzas", since=NOW - timedelta(days=7),
                          until=NOW, include_suppressed=False)
    assert default["total"] == 12 and without["total"] == 9


def test_min_score_excludes_null_scores_rather_than_treating_them_as_zero(seeded):
    """A null score is an absence, not a zero. It cannot satisfy a minimum, and
    it must not be coerced into one either."""
    page = list_events(seeded, "matanzas", since=NOW - timedelta(days=7),
                       until=NOW, min_score=0.6)
    assert all(i["score"] is not None and i["score"] >= 0.6 for i in page["items"])
    unfiltered = list_events(seeded, "matanzas", since=NOW - timedelta(days=7), until=NOW)
    assert any(i["score"] is None for i in unfiltered["items"])


def test_window_bounds_are_respected(seeded):
    page = list_events(seeded, "matanzas",
                       since=NOW - timedelta(hours=3), until=NOW)
    assert page["total"] == 4          # hours 0,1,2,3


# --- the naive-timestamp 500 this replaces -----------------------------------

def test_a_naive_since_does_not_raise(seeded):
    """The previous implementation compared a naive bound against an aware value
    and raised `TypeError` outside its guard, surfacing as an unhandled 500
    (R-5.6). A missing offset is now read as UTC."""
    naive = list_events(seeded, "matanzas",
                        since=(NOW - timedelta(hours=3)).replace(tzinfo=None),
                        until=NOW.replace(tzinfo=None))
    assert naive["total"] == 4


# --- freshness, and cross-site ----------------------------------------------

def test_index_updated_utc_reports_freshness(seeded):
    page = list_events(seeded, "matanzas", since=NOW - timedelta(days=7), until=NOW)
    assert page["index_updated_utc"] is not None


def test_index_updated_utc_is_null_when_nothing_has_been_indexed(db):
    """Null rather than a timestamp, because "no detections" and "no data
    reaching us" look identical to a reader and mean opposite things."""
    page = list_events(db, "matanzas", since=NOW - timedelta(days=7), until=NOW)
    assert page["total"] == 0 and page["index_updated_utc"] is None


def test_cross_site_query(db):
    """Expressible at all only because of the index (R-12.7)."""
    index_event(db, make(NOW, "a-000000-4000-8000-000000000001"), via=VIA_PUSH)
    index_event(db, make(NOW, "b-000000-4000-8000-000000000002", site="zapallar"),
                via=VIA_PUSH)
    db.commit()
    page = list_events(db, ["matanzas", "zapallar"],
                       since=NOW - timedelta(days=1), until=NOW)
    assert page["total"] == 2
    assert {i["site"] for i in page["items"]} == {"matanzas", "zapallar"}
