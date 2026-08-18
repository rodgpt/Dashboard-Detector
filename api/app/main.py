"""OceanKind dashboard API.

FastAPI serving a TypeScript frontend from one container. Owns users, sessions,
secrets and storage access. Depends on no cloud provider's identity or runtime,
so it moves to AWS or a bare server by changing environment variables (R-1).
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.db import init_db
from app.routers import auth, admin, data, devices

WEB_DIR = Path("/web")


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


# frontend last, so /api/* always wins
if WEB_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        # /login and /admin resolve to their own pages; anything else that is not
        # a real file falls back to the dashboard. Resolved and containment-checked
        # so a raw ../ in the request path cannot escape /web.
        base = WEB_DIR.resolve()
        if full_path:
            for candidate in (WEB_DIR / full_path, WEB_DIR / f"{full_path}.html"):
                try:
                    resolved = candidate.resolve()
                except OSError:
                    continue
                if resolved.is_file() and resolved.is_relative_to(base):
                    return FileResponse(resolved)
        return FileResponse(WEB_DIR / "index.html")
