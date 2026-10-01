"""`event_summary` backs the Detecciones charts over the whole filtered window.

The charts used to bucket whatever page `list_events` returned, which silently
turned "last 30 days" into "the newest 50 events" the moment a period held
more than one page. These tests assert the fix: counts cover the period asked
for regardless of `limit`/`offset`, and the same filters as `list_events`
apply identically, so the chart and the table can no longer disagree about
what period they describe.
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
from app.services.events import event_summary, list_events
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
    """120 events over five days (24/day), well past one page (`limit=50`)."""
    for i in range(120):
        index_event(db, make(
            NOW - timedelta(hours=i), f"e{i:03d}-0000-4000-8000-{i:012d}",
            event_type="blast" if i % 3 == 0 else "vessel",
            score=None if i % 11 == 0 else round(0.5 + (i % 10) * 0.04, 2),
            suppressed=(i % 4 == 0),
        ), via=VIA_PUSH)
    db.commit()
    return db


def test_covers_the_whole_period_not_one_page(seeded):
    """The regression this exists to fix: a page-sized table must not cap a
    period-sized chart."""
    page = list_events(seeded, "matanzas", since=NOW - timedelta(days=5), until=NOW)
    assert page["total"] == 120 and len(page["items"]) == 50   # one page, capped

    summary = event_summary(seeded, "matanzas", since=NOW - timedelta(days=5), until=NOW)
    assert summary["total"] == 120                             # the whole period


def test_by_hour_has_24_buckets_summing_to_the_total(seeded):
    summary = event_summary(seeded, "matanzas", since=NOW - timedelta(days=5), until=NOW)
    assert len(summary["by_hour"]) == 24
    assert sum(summary["by_hour"]) == summary["total"]


def test_by_day_is_sorted_and_sums_to_the_total(seeded):
    summary = event_summary(seeded, "matanzas", since=NOW - timedelta(days=5), until=NOW)
    dates = [row["date"] for row in summary["by_day"]]
    assert dates == sorted(dates)
    assert sum(row["count"] for row in summary["by_day"]) == summary["total"]


def test_empty_window_returns_zeroed_buckets_not_an_error(db):
    summary = event_summary(db, "matanzas", since=NOW - timedelta(days=1), until=NOW)
    assert summary == {"by_day": [], "by_hour": [0] * 24, "total": 0}


def test_filters_match_list_events_exactly(seeded):
    """Same predicate as the table, so the chart and the table can never
    disagree about what counts — unlike the legacy dashboard's two alert
    counters, which used different filters and silently diverged."""
    for kwargs in (
        {"event_type": "blast"},
        {"min_score": 0.6},
        {"include_suppressed": False},
    ):
        page = list_events(seeded, "matanzas", since=NOW - timedelta(days=5),
                           until=NOW, limit=500, **kwargs)
        summary = event_summary(seeded, "matanzas", since=NOW - timedelta(days=5),
                                until=NOW, **kwargs)
        assert summary["total"] == page["total"] == len(page["items"]), kwargs


def test_window_bounds_are_respected(seeded):
    summary = event_summary(seeded, "matanzas",
                            since=NOW - timedelta(hours=3), until=NOW)
    assert summary["total"] == 4   # hours 0,1,2,3


def test_cross_site_query(db):
    index_event(db, make(NOW, "a-000000-4000-8000-000000000001"), via=VIA_PUSH)
    index_event(db, make(NOW, "b-000000-4000-8000-000000000002", site="zapallar"),
                via=VIA_PUSH)
    db.commit()
    summary = event_summary(db, ["matanzas", "zapallar"],
                            since=NOW - timedelta(days=1), until=NOW)
    assert summary["total"] == 2
