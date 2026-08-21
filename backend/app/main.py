"""OceanKind dashboard API.

JSON only. This service serves no HTML and no static assets — the `frontend`
container does that and proxies `/api/` here (R-9.3, D-019). If you are about to
add `StaticFiles` or a `FileResponse` below, that is the old single-container
shape reasserting itself; don't.

Owns users, sessions, secrets and storage access. Depends on no cloud provider's
identity or runtime, so it moves to AWS or a bare server by changing environment
variables (R-1).
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from app.core.config import settings
from app.core.database import init_db
from app.routers import auth, admin, data, devices


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings().validate_runtime()      # fail fast and loudly on missing secrets (R-4.3)
    init_db()
    yield


app = FastAPI(title="OceanKind", version="2.0.0", lifespan=lifespan)

app.include_router(auth.router,    prefix="/api/auth",    tags=["auth"])
app.include_router(admin.router,   prefix="/api/admin",   tags=["admin"])
app.include_router(data.router,    prefix="/api",         tags=["data"])
app.include_router(devices.router, prefix="/api/devices", tags=["devices"])


class Health(BaseModel):
    status: str
    storage: str


@app.get("/api/health", tags=["ops"], response_model=Health)
def health():
    return {"status": "ok", "storage": settings().storage_backend}


# No catch-all route. An unknown path is a 404 from FastAPI, which is correct:
# nginx owns everything that is not /api/, including the SPA fallback.
