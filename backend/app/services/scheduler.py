"""Running the reconcile pass on a timer, and recording that it ran.

**A reconcile that nobody runs is not a correctness mechanism, it is a function.**
Until this existed the index stayed correct only for as long as somebody
remembered to invoke it by hand, which is the same as not being correct.

Why an asyncio task rather than a scheduler library or a cloud trigger
----------------------------------------------------------------------
A cron product (Azure Container Apps jobs, EventBridge, Cloud Scheduler) would be
a cloud-specific runtime dependency, which R-1.1 and R-1.4 forbid — the same
objection that removed Event Grid in D-022. APScheduler or Celery would be a
dependency and a second process for one periodic call. An asyncio task in the
application's own lifespan needs neither, and moves to any host that runs the
container.

The cost of that choice, stated: the timer lives and dies with the process, and
it assumes **one replica**. A second replica means two timers — harmless, because
`index_event` is idempotent (R-12.3), but wasteful. The deployment is already
pinned to one replica for the login throttle (`core/rate_limit.py`), so this adds
no new constraint; it does mean lifting that pin later has to account for both.

**Every run is recorded, including a failed one** (`IndexerRun`). A pass that has
been crashing for a week must not look the same as a pass that keeps finding
nothing, and from the outside those are identical unless the attempt itself is
written down.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from app.core.config import settings
from app.core.database import engine
from app.core.models import IndexerRun, Site
from app.services.reconcile import DEFAULT_WINDOW_DAYS, reconcile_site
from app.services.sites import registry
from app.services.storage import get_storage

log = logging.getLogger(__name__)

# Wait before the first pass so startup is not competing with it. Short enough
# that a restart still reconciles promptly, long enough that the app is serving
# first.
STARTUP_DELAY_S = 30


def _site_ids(db: Session) -> list[str]:
    rows = db.exec(select(Site.site_id).where(Site.active == True)).all()  # noqa: E712
    if rows:
        return list(rows)
    # Fall back to the storage registry, so a fixture tree with no managed sites
    # still reconciles. Same precedence rule the sites API uses.
    items, _source = registry(db)
    return [s["id"] for s in items if s.get("id")]


def run_once(site_id: str, *, window_days: int = DEFAULT_WINDOW_DAYS,
             trigger: str = "scheduled") -> IndexerRun:
    """Reconcile one site and record the attempt.

    Opens its own session deliberately: this runs on a timer with no request
    behind it, and must not borrow a request-scoped session's lifetime.
    """
    with Session(engine()) as db:
        run = IndexerRun(site_id=site_id, window_days=window_days, trigger=trigger)
        try:
            result = reconcile_site(db, get_storage(), site_id, days=window_days)
            run.blobs_in_storage = result.blobs_in_storage
            run.newly_indexed = result.newly_indexed
            run.conflicting = result.conflicting
            run.rejected = sum(d.rejected for d in result.days)
            run.drift = result.drift
        except Exception as e:                              # noqa: BLE001
            # Recorded, not swallowed. The pass failing silently is the failure
            # this whole subsystem exists to prevent.
            log.exception("reconcile failed for %s", site_id)
            run.error = f"{type(e).__name__}: {e}"[:500]
            db.rollback()
        run.finished_utc = datetime.now(timezone.utc)
        db.add(run)
        db.commit()
        db.refresh(run)
        return run


def run_all(*, window_days: int = DEFAULT_WINDOW_DAYS,
            trigger: str = "scheduled") -> list[IndexerRun]:
    """Reconcile every active site. One site failing never stops the others."""
    with Session(engine()) as db:
        sites = _site_ids(db)
    return [run_once(s, window_days=window_days, trigger=trigger) for s in sites]


async def _loop(interval_s: float, window_days: int) -> None:
    await asyncio.sleep(STARTUP_DELAY_S)
    while True:
        try:
            # `reconcile_site` is synchronous and does blocking I/O, so it goes
            # to a worker thread. Running it on the event loop would stall every
            # request for the duration of the pass.
            runs = await asyncio.to_thread(run_all, window_days=window_days)
            bad = [r for r in runs if not r.ok]
            if bad:
                log.warning(
                    "reconcile: %d/%d site(s) unhealthy: %s", len(bad), len(runs),
                    ", ".join(f"{r.site_id}(drift={r.drift},err={r.error})" for r in bad))
            else:
                log.info("reconcile: %d site(s) clean", len(runs))
        except asyncio.CancelledError:
            raise
        except Exception:                                   # noqa: BLE001
            # The timer must survive a bad pass. A scheduler that dies on its
            # first exception is worse than no scheduler, because the logs go
            # quiet and quiet reads as healthy.
            log.exception("reconcile loop iteration failed")
        await asyncio.sleep(interval_s)


def check_silence_once(now=None) -> list:
    """One pass of the device-silence check across every site (R-7.5).

    Separate timer from the reconcile, and much faster, because the two answer
    different questions. Reconcile asks "is the index complete?", which is a
    daily concern. This asks "is the unit alive?", where a day late is useless —
    the point is to reach someone before the morning.

    Cheap enough to run often: one small blob per site. How often anyone is
    *notified* is a different setting entirely; see `services/silence.py`.
    """
    from app.services import silence
    with Session(engine()) as db:
        sites = _site_ids(db)
        return silence.check_all(db, get_storage(), sites, now=now)


async def _silence_loop(interval_s: float) -> None:
    await asyncio.sleep(STARTUP_DELAY_S)
    while True:
        try:
            results = await asyncio.to_thread(check_silence_once)
            noisy = [r for r in results if r.outcome not in ("ok",)]
            if noisy:
                log.info("silence check: %s",
                         ", ".join(f"{r.site_id}={r.outcome}" for r in noisy))
        except asyncio.CancelledError:
            raise
        except Exception:                                       # noqa: BLE001
            log.exception("silence loop iteration failed")
        await asyncio.sleep(interval_s)


_task: Optional[asyncio.Task] = None
_silence_task: Optional[asyncio.Task] = None


def start() -> Optional[asyncio.Task]:
    """Start the timer, unless it is switched off.

    `OCEANKIND_RECONCILE_INTERVAL_HOURS=0` disables it — for tests, and for a
    deployment that drives the pass from outside the process. Disabling is
    logged at warning level: an index with no reconcile is a supported
    configuration, but never an accidental one.
    """
    global _task
    s = settings()

    # Started first, and independently. These two timers answer different
    # questions and must not share a fate: switching the reconcile off — which
    # tests do, and a deployment driving it externally would — must not silently
    # take device-silence alerting with it.
    _start_silence()

    hours = s.reconcile_interval_hours
    if hours <= 0:
        log.warning("reconcile scheduler disabled (OCEANKIND_RECONCILE_INTERVAL_HOURS=0); "
                    "the index will only be correct if something else runs the pass")
        return None
    _task = asyncio.create_task(_loop(hours * 3600, s.reconcile_window_days))
    log.info("reconcile scheduler started: every %sh over a %sd window",
             hours, s.reconcile_window_days)
    return _task


def _start_silence() -> None:
    global _silence_task
    s = settings()
    if not s.silence_alerts_enabled:
        log.warning("device-silence alerting disabled "
                    "(OCEANKIND_SILENCE_ALERTS_ENABLED=false); a unit that stops "
                    "reporting will only be visible to somebody with the page open")
        return
    _silence_task = asyncio.create_task(
        _silence_loop(s.silence_check_interval_minutes * 60))
    log.info("silence check started: every %s min, warn after %s missed heartbeats "
             "(floor %s min), repeat every %sh",
             s.silence_check_interval_minutes, s.silence_after_missed_heartbeats,
             s.silence_min_minutes, s.silence_renotify_hours)


async def stop() -> None:
    global _task, _silence_task
    for name in ("_task", "_silence_task"):
        task = globals()[name]
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):     # noqa: BLE001
                pass
            globals()[name] = None
