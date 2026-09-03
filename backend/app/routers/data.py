"""Everything the dashboard reads. Every route is authenticated and site-scoped.

The browser never touches storage and never holds a credential (R-4.2, R-5.5).
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel
from sqlmodel import Session

from app.core.config import settings
from app.core.database import get_session
from app.core.models import User
from app.core.security import current_user, assert_site_allowed, allowed_sites
from app.services.storage import get_storage
from app.services.events import list_events, read_json, read_json_with_etag

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
    # Replaces `scanned_blobs`, which described work this endpoint no longer does
    # (D-021). Null means nothing has ever been indexed for these sites — a
    # fresh deployment, or an indexer that has not run. Worth showing: "no
    # detections" and "no data reaching us" look identical and mean opposite
    # things.
    index_updated_utc: Optional[str] = None


@router.get("/sites", response_model=SitesOut)
def sites(user: User = Depends(current_user), db: Session = Depends(get_session)):
    """Only the sites this user may see. The list itself is a permission boundary."""
    from app.services.sites import registry
    items, _source = registry(db)
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
    """Paginated and filtered. The browser gets a page, never the history (R-5.1).

    Served from the derived index, so this costs one query and no reads against
    object storage regardless of the window (D-021, R-12.1).
    """
    assert_site_allowed(site_id, user, db)
    return list_events(db, site_id, since, until, event_type,
                       min_score, include_suppressed, limit, offset)


def _rollup(site_id: str, name: str, user: User, db: Session,
            request: Request, response: Response):
    """A rollup blob, with conditional-request support (R-5.7).

    These are polled continuously and change rarely, so an unchanged rollup
    should cost a 304 and no body. That matters on a cellular-connected phone,
    which is the field condition, not an edge case (F-18).
    """
    assert_site_allowed(site_id, user, db)
    doc, etag = read_json_with_etag(get_storage(), f"sites/{site_id}/{name}")
    if doc is None:
        # absent or malformed: say so, do not fabricate and do not 500 (R-7.3)
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{name} unavailable for this site")

    if etag:
        response.headers["ETag"] = etag
        # Rollups are overwritten in place, so a client that already has these
        # bytes needs nothing back.
        response.headers["Cache-Control"] = "no-cache"
        if request.headers.get("if-none-match") == etag:
            response.status_code = status.HTTP_304_NOT_MODIFIED
            return Response(status_code=status.HTTP_304_NOT_MODIFIED,
                            headers={"ETag": etag, "Cache-Control": "no-cache"})
    return doc


@router.get("/sites/{site_id}/status")
def status_(site_id: str, request: Request, response: Response,
       user: User = Depends(current_user), db: Session = Depends(get_session)):
    return _rollup(site_id, "status.json", user, db, request, response)


@router.get("/sites/{site_id}/power")
def power(site_id: str, request: Request, response: Response,
       user: User = Depends(current_user), db: Session = Depends(get_session)):
    return _rollup(site_id, "power_history.json", user, db, request, response)


@router.get("/sites/{site_id}/acoustic")
def acoustic(site_id: str, request: Request, response: Response,
       user: User = Depends(current_user), db: Session = Depends(get_session)):
    return _rollup(site_id, "acoustic_indicators.json", user, db, request, response)


@router.get("/sites/{site_id}/ocean")
def ocean(site_id: str, request: Request, response: Response,
       user: User = Depends(current_user), db: Session = Depends(get_session)):
    return _rollup(site_id, "ocean_conditions.json", user, db, request, response)


@router.get("/sites/{site_id}/clips/{path:path}")
def clip(site_id: str, path: str, user: User = Depends(current_user),
         db: Session = Depends(get_session)):
    """Audio proxied through the API, so the container stays private (R-5.4)."""
    assert_site_allowed(site_id, user, db)
    blob = f"sites/{site_id}/clips/{path}"
    storage = get_storage()
    if not storage.exists(blob):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "clip not found")
    return Response(storage.get(blob), media_type="audio/wav")
