"""Everything the dashboard reads. Every route is authenticated and site-scoped.

The browser never touches storage and never holds a credential (R-4.2, R-5.5).
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlmodel import Session

from app.core.config import settings
from app.core.db import get_session
from app.core.models import User
from app.core.security import current_user, assert_site_allowed, allowed_sites
from app.services.storage import get_storage
from app.services.events import list_events, read_json

router = APIRouter()


# The envelopes below are ours, so they are typed and appear in the generated schema.
# The blobs inside `items` are the device's and stay `dict`: a response_model over them
# would silently drop any field the device adds ahead of the dashboard, which is the
# opposite of what DATA-CONTRACT.md requires (unknown fields are surfaced, not eaten).

class SitesOut(BaseModel):
    sites: list[dict]


class EventsPage(BaseModel):
    items: list[dict]
    total: int
    limit: int
    offset: int
    has_more: bool
    scanned_blobs: int
    # LEGACY-V1-BEGIN
    # Set only by the v1 source: tells the client which fields could not be
    # recovered, so it labels them instead of rendering a guess.
    contract: dict | None = None
    # LEGACY-V1-END


@router.get("/sites", response_model=SitesOut)
def sites(user: User = Depends(current_user), db: Session = Depends(get_session)):
    """Only the sites this user may see. The list itself is a permission boundary."""
    doc = read_json(get_storage(), "_sites.json") or {"sites": []}
    items = doc.get("sites", [])
    if user.role != "admin":
        permitted = set(allowed_sites(user, db))
        items = [s for s in items if s.get("id") in permitted]
    return {"sites": items}


@router.get("/sites/{site_id}/events", response_model=EventsPage)
def events(
    site_id: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    event_type: Optional[str] = Query(None, pattern="^(vessel|blast|unknown)$"),
    min_score: float = Query(0.0, ge=0.0, le=1.0),
    include_suppressed: bool = True,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    """Paginated and filtered. The browser gets a page, never the history (R-5.1)."""
    assert_site_allowed(site_id, user, db)
    return list_events(get_storage(), site_id, since, until, event_type,
                       min_score, include_suppressed, limit, offset)


def _rollup(site_id: str, name: str, user: User, db: Session):
    assert_site_allowed(site_id, user, db)
    doc = read_json(get_storage(), f"sites/{site_id}/{name}")
    if doc is None:
        # absent or malformed: say so, do not fabricate and do not 500 (R-7.3)
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{name} unavailable for this site")
    return doc


@router.get("/sites/{site_id}/status")
def status_(site_id: str, user: User = Depends(current_user), db: Session = Depends(get_session)):
    return _rollup(site_id, "status.json", user, db)


@router.get("/sites/{site_id}/power")
def power(site_id: str, user: User = Depends(current_user), db: Session = Depends(get_session)):
    return _rollup(site_id, "power_history.json", user, db)


@router.get("/sites/{site_id}/acoustic")
def acoustic(site_id: str, user: User = Depends(current_user), db: Session = Depends(get_session)):
    return _rollup(site_id, "acoustic_indicators.json", user, db)


@router.get("/sites/{site_id}/ocean")
def ocean(site_id: str, user: User = Depends(current_user), db: Session = Depends(get_session)):
    return _rollup(site_id, "ocean_conditions.json", user, db)


@router.get("/sites/{site_id}/clips/{path:path}")
def clip(site_id: str, path: str, user: User = Depends(current_user),
         db: Session = Depends(get_session)):
    """Audio proxied through the API, so the container stays private (R-5.4)."""
    assert_site_allowed(site_id, user, db)
    blob = f"sites/{site_id}/clips/{path}"
    # LEGACY-V1-BEGIN
    if settings().contract_version == 1:
        from app.services import legacy_v1
        blob = legacy_v1.clip_blob(site_id, path, settings().v1_root_site)
    # LEGACY-V1-END
    storage = get_storage()
    if not storage.exists(blob):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "clip not found")
    return Response(storage.get(blob), media_type="audio/wav")
