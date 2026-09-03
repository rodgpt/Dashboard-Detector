"""Drift surfaced, the pass recorded, and the index provably derived.

R-12.2 and R-12.5. These are the tests that stop the index quietly becoming a
second source of truth, and that stop a reconcile which has not run for a week
from looking exactly like one that keeps finding nothing.
"""
import os, tempfile, json, pathlib

for _k, _v in {
    "OCEANKIND_SESSION_SECRET": "x" * 40,
    "OCEANKIND_STORAGE_BACKEND": "local",
    "OCEANKIND_LOCAL_STORAGE_ROOT": tempfile.mkdtemp(),
    "OCEANKIND_DB_URL": f"sqlite:///{tempfile.mktemp()}",
    "OCEANKIND_COOKIE_SECURE": "false",
    "OCEANKIND_CONFIG_HMAC_KEY": "test-signing-key-0123456789abcdef",
    "OCEANKIND_RECONCILE_INTERVAL_HOURS": "0",
}.items():
    os.environ.setdefault(_k, _v)

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, select

from app.main import app
from app.core.database import init_db, engine
from app.core.models import DetectionEvent, IndexerRun, Site, User
from app.core.security import hash_password
from app.services import scheduler
from app.services.storage import get_storage

SITE = "matanzas"
NOW = datetime.now(timezone.utc)

root = pathlib.Path(os.environ["OCEANKIND_LOCAL_STORAGE_ROOT"])
root.mkdir(parents=True, exist_ok=True)
if not (root / "_sites.json").exists():
    (root / "_sites.json").write_text(json.dumps({"schema_version": 2, "sites": [
        {"id": SITE, "name": "Matanzas", "lat": 0, "lon": 0, "device": "b", "active": True},
    ]}))


def blob(captured: datetime, event_id: str) -> None:
    doc = {
        "schema_version": 2, "site": SITE, "device": "Rpi_matanzas",
        "event_id": event_id, "captured_utc": captured.isoformat(),
        "event_type": "vessel", "detector": "psd_tonal", "score": 0.7,
        "suppressed": False,
    }
    path = (root / f"sites/{SITE}/events/{captured:%Y/%m/%d}/"
                   f"{captured:%Y-%m-%dT%H-%M-%S}_{event_id}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))


@pytest.fixture(scope="module")
def admin():
    init_db()
    SQLModel.metadata.create_all(engine())
    with Session(engine()) as db:
        if not db.exec(select(User).where(User.email == "ix@x.io")).first():
            db.add(User(email="ix@x.io",
                        password_hash=hash_password("correct-horse-battery"), role="admin"))
        if not db.get(Site, SITE):
            db.add(Site(site_id=SITE, name="Matanzas"))
        db.commit()
    c = TestClient(app)
    c.post("/api/auth/login", json={"email": "ix@x.io", "password": "correct-horse-battery"})
    return c


@pytest.fixture(autouse=True)
def clean():
    with Session(engine()) as s:
        for row in s.exec(select(DetectionEvent)).all():
            s.delete(row)
        for row in s.exec(select(IndexerRun)).all():
            s.delete(row)
        s.commit()
    for p in (root / f"sites/{SITE}/events").rglob("*.json"):
        p.unlink()
    yield


# --- drift is visible, per day and per site (R-12.5) ------------------------

def test_drift_is_reported_and_attributed_to_a_day(admin):
    day = NOW - timedelta(days=3)
    blob(day, "drift-0000-4000-8000-000000000001")

    body = admin.get("/api/admin/index").json()
    site = next(s for s in body if s["site_id"] == SITE)
    assert site["drift"] == 1
    assert len(site["days_with_drift"]) == 1
    assert site["days_with_drift"][0]["day"] == day.date().isoformat()


def test_drift_clears_after_a_reconcile(admin):
    blob(NOW, "clear-0000-4000-8000-000000000002")
    assert next(s for s in admin.get("/api/admin/index").json()
                if s["site_id"] == SITE)["drift"] == 1

    r = admin.post("/api/admin/index/reconcile", params={"site_id": SITE})
    assert r.status_code == 200
    assert r.json()[0]["newly_indexed"] == 1 and r.json()[0]["ok"] is True

    assert next(s for s in admin.get("/api/admin/index").json()
                if s["site_id"] == SITE)["drift"] == 0


def test_never_having_run_is_distinguishable_from_running_clean(admin):
    """An index with zero drift that has never been checked is not the same as
    one checked an hour ago, and only one of them is evidence of anything."""
    before = next(s for s in admin.get("/api/admin/index").json() if s["site_id"] == SITE)
    assert before["last_run_utc"] is None and before["last_run_ok"] is None

    admin.post("/api/admin/index/reconcile", params={"site_id": SITE})

    after = next(s for s in admin.get("/api/admin/index").json() if s["site_id"] == SITE)
    assert after["last_run_utc"] is not None
    assert after["last_run_ok"] is True
    assert after["last_run_trigger"] == "manual"


def test_the_index_view_is_closed_to_operators(admin):
    """Site scoping is not the only boundary: the index view exposes every site,
    so it is admin-only like the rest of /api/admin."""
    with Session(engine()) as db:
        if not db.exec(select(User).where(User.email == "op2@x.io")).first():
            db.add(User(email="op2@x.io",
                        password_hash=hash_password("correct-horse-battery"),
                        role="operator"))
            db.commit()
    c = TestClient(app)
    c.post("/api/auth/login", json={"email": "op2@x.io", "password": "correct-horse-battery"})
    assert c.get("/api/admin/index").status_code == 403
    assert c.post("/api/admin/index/reconcile").status_code == 403


# --- every pass is recorded, including a failed one --------------------------

def test_a_failing_pass_is_recorded_not_swallowed(monkeypatch):
    """'The reconcile has been crashing for a week' must not look like 'the
    reconcile keeps finding nothing'. From the outside they are identical unless
    the attempt itself is written down."""
    import app.services.scheduler as sched

    def boom(*a, **k):
        raise RuntimeError("storage unreachable")

    monkeypatch.setattr(sched, "reconcile_site", boom)
    run = scheduler.run_once(SITE, trigger="manual")

    assert run.error is not None and "storage unreachable" in run.error
    assert run.ok is False
    with Session(engine()) as db:
        assert db.exec(select(IndexerRun)).one().error is not None


def test_run_all_covers_every_site_and_records_each():
    """Every registered site, not just the one this module cares about — the
    suite shares a database, so others are present and must be covered too. One
    row per site per pass, so a site that was skipped is visible by absence."""
    runs = scheduler.run_all(trigger="manual")
    assert SITE in {r.site_id for r in runs}
    assert len(runs) >= 1
    with Session(engine()) as db:
        recorded = db.exec(select(IndexerRun)).all()
    assert len(recorded) == len(runs)
    assert {r.site_id for r in recorded} == {r.site_id for r in runs}


# --- the index is provably derived (R-12.2) ---------------------------------

def test_rebuild_reproduces_the_same_answers(admin):
    """*Drop the index, rebuild from the container, and every query returns what
    it returned before.* If a rebuild cannot reproduce it, something existed only
    in Postgres and the index had become a second source of truth."""
    for i in range(6):
        blob(NOW - timedelta(hours=i), f"rb{i}-0000-4000-8000-00000000000{i}")
    admin.post("/api/admin/index/reconcile", params={"site_id": SITE})

    before = admin.get(f"/api/sites/{SITE}/events", params={"limit": 50}).json()
    assert before["total"] == 6

    r = admin.post("/api/admin/index/rebuild",
                   json={"site_id": SITE, "confirm_site_id": SITE})
    assert r.status_code == 200 and r.json()["newly_indexed"] == 6

    after = admin.get(f"/api/sites/{SITE}/events", params={"limit": 50}).json()
    assert [i["event_id"] for i in after["items"]] == [i["event_id"] for i in before["items"]]
    assert after["total"] == before["total"]


def test_rebuild_requires_confirmation(admin):
    """A destructive action that needs no confirmation is one somebody performs
    by accident while looking at something else."""
    blob(NOW, "conf-0000-4000-8000-000000000010")
    admin.post("/api/admin/index/reconcile", params={"site_id": SITE})

    r = admin.post("/api/admin/index/rebuild",
                   json={"site_id": SITE, "confirm_site_id": "something-else"})
    assert r.status_code == 400
    with Session(engine()) as db:
        assert len(db.exec(select(DetectionEvent)).all()) == 1, "rows dropped anyway"
