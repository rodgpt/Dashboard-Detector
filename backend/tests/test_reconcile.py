"""The reconcile pass (R-12.4, R-12.5).

The tests that matter are the ones about *not noticing*. A reconcile that indexes
the obvious cases and quietly misses the late-arriving one produces a dashboard
that looks perfectly healthy while under-reporting detections, which is the exact
failure this system exists to prevent.
"""
import os, tempfile, json, pathlib, shutil

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
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, SQLModel, select

from app.core.database import engine
from app.core.models import DetectionEvent
from app.services.indexer import index_event, VIA_PUSH
from app.services.reconcile import (
    DEFAULT_WINDOW_DAYS, event_id_from_name, measure_drift, reconcile_site,
)
from app.services.storage import LocalStorage

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
SITE = "matanzas"


@pytest.fixture()
def storage(tmp_path):
    return LocalStorage(str(tmp_path))


@pytest.fixture()
def db():
    SQLModel.metadata.create_all(engine())
    with Session(engine()) as s:
        for row in s.exec(select(DetectionEvent)).all():
            s.delete(row)
        s.commit()
        yield s


def make_event(captured: datetime, event_id: str, **over) -> dict:
    return {
        "schema_version": 2, "site": SITE, "device": "Rpi_matanzas",
        "event_id": event_id,
        "captured_utc": captured.isoformat(),
        "generated_utc": captured.isoformat(),
        "event_type": "vessel", "detector": "psd_tonal", "score": 0.71,
        "suppressed": False,
        "clip": {"path": f"sites/{SITE}/clips/x.wav", "uploaded": True},
        **over,
    }


def write_blob(storage: LocalStorage, doc: dict, *, name: str | None = None) -> str:
    """Write an event where the device would put it: partitioned on captured_utc."""
    captured = datetime.fromisoformat(doc["captured_utc"]).astimezone(timezone.utc)
    stem = name or f"{captured:%Y-%m-%dT%H-%M-%S}_{doc['event_id']}.json"
    path = f"sites/{SITE}/events/{captured:%Y/%m/%d}/{stem}"
    storage.put(path, json.dumps(doc).encode())
    return path


# --- the failure a high-water mark cannot survive ---------------------------

def test_an_event_landing_in_a_past_prefix_is_still_found(db, storage):
    """**The high-water-mark trap.** Index up to today, then have a spooled event
    drain into a prefix three days back. A mark would have advanced past that
    partition and never looked again — the event would be unreachable,
    permanently and silently. The trailing window is what makes it findable."""
    write_blob(storage, make_event(NOW, "today-0000-4000-8000-000000000001"))
    first = reconcile_site(db, storage, SITE, now=NOW)
    assert first.newly_indexed == 1
    assert first.drift == 0

    # ...and now Tuesday's event arrives on the Friday
    late = NOW - timedelta(days=3)
    write_blob(storage, make_event(late, "late-0000-4000-8000-000000000002"))

    second = reconcile_site(db, storage, SITE, now=NOW)
    assert second.newly_indexed == 1, "a late arrival behind the newest day was missed"
    assert second.drift == 0
    with Session(engine()) as s:
        assert len(s.exec(select(DetectionEvent)).all()) == 2


def test_events_outside_the_window_are_not_claimed_as_indexed(db, storage):
    """Beyond the window the pass makes no claim at all — it does not report
    drift for days it never looked at. The window is a stated commitment about
    the longest outage survivable, not a silent boundary."""
    old = NOW - timedelta(days=DEFAULT_WINDOW_DAYS + 5)
    write_blob(storage, make_event(old, "old-00000-4000-8000-000000000003"))
    r = reconcile_site(db, storage, SITE, now=NOW)
    assert r.newly_indexed == 0
    assert r.blobs_in_storage == 0          # that prefix was never listed
    assert r.since > old.date()


# --- cost: the pass must not re-read what it already has --------------------

def test_steady_state_fetches_nothing(db, storage):
    """`event_id` is in the blob name, so a second pass diffs names against the
    index and opens nothing. This is what makes a fortnight window affordable."""
    for i in range(5):
        write_blob(storage, make_event(NOW - timedelta(days=i), f"e{i}-0000-4000-8000-00000000000{i}"))

    first = reconcile_site(db, storage, SITE, now=NOW)
    assert first.fetched == 5

    second = reconcile_site(db, storage, SITE, now=NOW)
    assert second.fetched == 0, "re-read blobs it had already indexed"
    assert second.newly_indexed == 0
    assert second.drift == 0


def test_a_pushed_event_is_not_refetched_by_the_pass(db, storage):
    """The normal case once the device is pushing: the pass confirms and costs
    nothing. It also must not overwrite how the event first arrived."""
    doc = make_event(NOW, "push-0000-4000-8000-000000000004")
    index_event(db, doc, via=VIA_PUSH)
    db.commit()
    write_blob(storage, doc)

    r = reconcile_site(db, storage, SITE, now=NOW)
    assert r.fetched == 0 and r.newly_indexed == 0 and r.drift == 0
    with Session(engine()) as s:
        assert s.exec(select(DetectionEvent)).one().first_seen_via == "push"


def test_the_pass_never_opens_a_clip(db, storage, monkeypatch):
    """An event JSON is ~600 bytes against ~960 KB of WAV. A pass that touched
    audio would be three orders of magnitude more expensive, so this is asserted
    rather than assumed."""
    write_blob(storage, make_event(NOW, "clip-0000-4000-8000-000000000005"))
    storage.put(f"sites/{SITE}/clips/2026/08/26/whatever.wav", b"RIFF....")

    opened: list[str] = []
    real_get = storage.get
    monkeypatch.setattr(storage, "get", lambda p: (opened.append(p), real_get(p))[1])

    reconcile_site(db, storage, SITE, now=NOW)
    assert opened and not any(p.endswith(".wav") for p in opened)


# --- malformed input must be counted and surfaced, never silently skipped ----

def test_a_malformed_blob_is_counted_and_does_not_stall_the_pass(db, storage):
    write_blob(storage, make_event(NOW, "good-0000-4000-8000-000000000006"))
    storage.put(f"sites/{SITE}/events/{NOW:%Y/%m/%d}/"
                f"{NOW:%Y-%m-%dT%H-%M-%S}_broken-0000-4000-8000-000000000007.json",
                b"{not json at all")

    r = reconcile_site(db, storage, SITE, now=NOW)
    assert r.newly_indexed == 1               # the good one still landed
    assert len(r.rejections) == 1
    assert not r.healthy                      # and it is visible, not swallowed
    assert r.drift == 1                       # the blob exists with no row


def test_a_naive_timestamp_in_a_blob_is_rejected_and_surfaced(db, storage):
    bad = make_event(NOW, "naive-0000-4000-8000-000000000008")
    bad["captured_utc"] = "2026-08-26T12:00:00"        # no offset
    storage.put(f"sites/{SITE}/events/2026/08/26/2026-08-26T12-00-00_"
                "naive-0000-4000-8000-000000000008.json", json.dumps(bad).encode())

    r = reconcile_site(db, storage, SITE, now=NOW)
    assert len(r.rejections) == 1
    assert "UTC offset" in r.rejections[0][1]
    assert r.newly_indexed == 0
    assert r.drift == 1              # the blob exists and has no row: a fault
    assert not r.healthy             # and the pass says so rather than passing


def test_an_unparseable_blob_name_is_fetched_not_assumed_indexed(db, storage):
    """A file whose name we cannot read for an `event_id` must be opened, never
    skipped. Guessing "probably already covered" is how events go missing."""
    doc = make_event(NOW, "odd-00000-4000-8000-000000000009")
    write_blob(storage, doc, name="no-underscore-here.json")

    r = reconcile_site(db, storage, SITE, now=NOW)
    assert r.fetched == 1 and r.newly_indexed == 1 and r.drift == 0


def test_two_blobs_claiming_one_event_id_is_a_fault_not_a_duplicate(db, storage):
    """Found against the real fixture tree, which had 45 of these.

    Two *different* documents sharing an `event_id`. Only one can hold the key,
    so the second blob's content is never indexed — and counting it as "already
    indexed" would let the pass report healthy over a tree it is silently
    under-representing. It stays drift, and it is named.

    No device can produce this (`event_id` is a uuid4 written once), which is
    exactly why it must be surfaced rather than absorbed: if it ever appears in
    production something upstream is badly wrong.
    """
    first = make_event(NOW, "dup-00000-4000-8000-000000000013")
    write_blob(storage, first)
    clash = make_event(NOW - timedelta(days=2), "dup-00000-4000-8000-000000000013",
                       event_type="blast")
    write_blob(storage, clash)

    r = reconcile_site(db, storage, SITE, now=NOW)
    assert r.blobs_in_storage == 2
    assert r.newly_indexed == 1
    assert r.conflicting == 1
    assert r.drift == 1                      # the second blob is not represented
    assert not r.healthy
    assert "already held by a different document" in r.rejections[0][1]

    # and it must not silently converge to healthy on a later pass
    again = reconcile_site(db, storage, SITE, now=NOW)
    assert again.conflicting == 1 and not again.healthy


def test_event_id_from_name_parses_the_contract_shape():
    assert event_id_from_name(
        "sites/x/events/2026/07/25/2026-07-25T18-16-18_ade4ac9f-d16d-4802-859b-95c75ecfd9bd.json"
    ) == "ade4ac9f-d16d-4802-859b-95c75ecfd9bd"
    assert event_id_from_name("sites/x/events/2026/07/25/nounderscore.json") is None
    assert event_id_from_name("sites/x/clips/2026/07/25/abc.wav") is None


# --- the drift metric (R-12.5) ----------------------------------------------

def test_drift_is_measurable_without_writing_anything(db, storage):
    write_blob(storage, make_event(NOW, "d1-00000-4000-8000-000000000010"))
    write_blob(storage, make_event(NOW - timedelta(days=2), "d2-00000-4000-8000-000000000011"))

    before = measure_drift(db, storage, SITE, now=NOW)
    assert before.drift == 2                  # nothing indexed yet
    with Session(engine()) as s:
        assert s.exec(select(DetectionEvent)).all() == []   # and nothing written

    reconcile_site(db, storage, SITE, now=NOW)
    after = measure_drift(db, storage, SITE, now=NOW)
    assert after.drift == 0 and after.healthy


def test_drift_is_attributed_to_the_day_it_happened(db, storage):
    """Per day and per site, so a bad day is locatable rather than a total that
    says only 'something is wrong somewhere'."""
    day = NOW - timedelta(days=4)
    write_blob(storage, make_event(day, "dd-00000-4000-8000-000000000012"))

    r = measure_drift(db, storage, SITE, now=NOW)
    drifting = r.days_with_drift
    assert len(drifting) == 1
    assert drifting[0].day == day.date()
    assert drifting[0].drift == 1


def test_an_empty_site_is_healthy_not_broken(db, storage):
    r = measure_drift(db, storage, SITE, now=NOW)
    assert r.drift == 0 and r.healthy and r.blobs_in_storage == 0
