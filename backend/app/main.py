"""OceanKind dashboard API.

JSON only. This service serves no HTML and no static assets — the `frontend`
container does that and proxies `/api/` here (R-9.3, D-019). If you are about to
add `StaticFiles` or a `FileResponse` below, that is the old single-container
shape reasserting itself; don't.

Owns users, sessions, secrets and storage access. Depends on no cloud provider's
identity or runtime, so it moves to AWS or a bare server by changing environment
variables (R-1).
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from app.core.config import settings
from app.core.database import init_db
from app.routers import auth, admin, data, devices
from app.services import scheduler


def _configure_logging() -> None:
    """Make our own logs visible.

    Without this the root logger sits at WARNING and every `log.info` in the
    application is discarded — including both "scheduler started" lines. That
    left the two timers the index and the silence alert depend on with no way to
    confirm they were running: an operator could not tell a working scheduler
    from one that never started, which is the failure mode this whole subsystem
    is built to prevent.

    `OCEANKIND_LOG_LEVEL` tunes it. WARNING and above still reaches the stream
    whatever it is set to, because that is where device alerts and drift
    warnings go.
    """
    level = getattr(logging, settings().log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        force=True,          # uvicorn has already configured handlers by now
    )
    # Access logs are uvicorn's and stay at its own level; ours are the app's.
    logging.getLogger("app").setLevel(level)


@asynccontextmanager
async def lifespan(_: FastAPI):
    _configure_logging()
    settings().validate_runtime()      # fail fast and loudly on missing secrets (R-4.3)
    # Build the storage client once, here, so a backend that cannot be
    # constructed fails the boot instead of every later request (review BE-07b).
    from app.services.storage import get_storage
    get_storage()
    if not settings().silence_webhook_url:
        # Not a secret and not optional to know: with no webhook, a device that
        # dies is a WARNING line in this log and a row in `device_alert` that the
        # dashboard now shows — but nobody is paged. Say so once, where an
        # operator reading the boot log will see it (review BE-05).
        logging.getLogger("app").warning(
            "OCEANKIND_SILENCE_WEBHOOK_URL is empty: device-silence alerts are recorded "
            "and shown in the dashboard but nobody is notified out of band")
    init_db()
    # The reconcile pass is the index's correctness mechanism (R-12.4), and one
    # that only runs when somebody remembers to call it is not a mechanism. In
    # process rather than a cloud scheduler, because a cloud trigger would be
    # exactly the runtime dependency R-1.1 forbids — see services/scheduler.py.
    scheduler.start()
    try:
        yield
    finally:
        await scheduler.stop()


app = FastAPI(title="OceanKind", version="2.0.0", lifespan=lifespan)

app.include_router(auth.router,    prefix="/api/auth",    tags=["auth"])
app.include_router(admin.router,   prefix="/api/admin",   tags=["admin"])
app.include_router(data.router,    prefix="/api",         tags=["data"])
app.include_router(devices.router, prefix="/api/devices", tags=["devices"])


class Health(BaseModel):
    status: str
    storage: str
    # "webhook" when device-silence alerts reach somebody out of band,
    # "log-only" when they are recorded and shown but nobody is paged (R-7.5).
    silence_alerts: str


@app.get("/api/health", tags=["ops"], response_model=Health)
def health():
    s = settings()
    return {"status": "ok", "storage": s.storage_backend,
            "silence_alerts": ("off" if not s.silence_alerts_enabled
                               else "webhook" if s.silence_webhook_url else "log-only")}


# No catch-all route. An unknown path is a 404 from FastAPI, which is correct:
# nginx owns everything that is not /api/, including the SPA fallback.
