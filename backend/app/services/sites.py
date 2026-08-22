"""The site registry.

One rule: **Postgres wins when it has rows; otherwise `_sites.json` in storage.**

Why both. The blob is what `DATA-CONTRACT.md` documents and what the fixture
tree ships, so a developer running `make dev` gets sites with no setup. But
nothing writes that blob outside the fixture generator, so a fresh private
container has no registry at all — which meant `/api/sites` returned nothing and
device registration rejected every site as unknown. The table fixes that without
breaking the documented shape, and without giving the backend write access to
storage for one use case.

The device never reads the registry. It writes to `sites/{site_id}/...` and
nothing else, so which side is authoritative is ours to choose.
"""
from typing import Literal

from sqlmodel import Session, select

from app.core.models import Site
from app.services.events import read_json
from app.services.storage import get_storage

Source = Literal["database", "storage", "empty"]


def _as_api(site: Site) -> dict:
    """The shape `_sites.json` documents, so the client sees one schema."""
    return {"id": site.site_id, "name": site.name, "lat": site.lat, "lon": site.lon,
            "device": site.device, "active": site.active}


def registry(db: Session) -> tuple[list[dict], Source]:
    """Every site, and where it came from. The source is surfaced to
    administrators so a storage-backed registry is visibly not yet managed."""
    rows = list(db.exec(select(Site)))
    if rows:
        return [_as_api(r) for r in sorted(rows, key=lambda r: r.site_id)], "database"

    doc = read_json(get_storage(), "_sites.json") or {}
    items = [s for s in doc.get("sites", []) if isinstance(s, dict) and s.get("id")]
    return (items, "storage") if items else ([], "empty")


def known_ids(db: Session) -> list[str]:
    """Valid `site_id` values. Device registration validates against this, so a
    typo cannot mint a credential for a site that never existed."""
    sites, _ = registry(db)
    return [s["id"] for s in sites]


def import_from_storage(db: Session) -> list[dict]:
    """Copy the storage registry into the table, once, explicitly.

    Deliberately not automatic at boot: silently materialising rows from a blob
    would make it unclear which side is authoritative, and the whole point of
    the table is that the answer is unambiguous.
    """
    doc = read_json(get_storage(), "_sites.json") or {}
    existing = {s.site_id for s in db.exec(select(Site))}
    added: list[dict] = []
    for item in doc.get("sites", []):
        if not isinstance(item, dict):
            continue
        sid = item.get("id")
        if not sid or sid in existing:
            continue
        site = Site(site_id=sid, name=item.get("name") or sid,
                    lat=item.get("lat"), lon=item.get("lon"),
                    device=item.get("device"), active=bool(item.get("active", True)))
        db.add(site)
        added.append(_as_api(site))
    db.commit()
    return added
