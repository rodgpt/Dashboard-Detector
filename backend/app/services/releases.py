"""Releases a device can be assigned (Rpi-Detector D-021).

A release is a git tag on the device repository. The admin panel offers the tags
GitHub lists, cached briefly, and also accepts a typed tag — the backend never
needs GitHub to work, only to be helpful. Validation is the contract's tag rule;
the device re-validates before passing the ref to its OTA.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from app.core.config import settings
from app.core.models import FleetRelease
from app.services.deviceconfig import TAG_RE

log = logging.getLogger(__name__)

_cache: dict = {"at": 0.0, "tags": []}
CACHE_S = 300


def valid_tag(value: Optional[str]) -> bool:
    return value is None or bool(TAG_RE.match(value))


def github_tags() -> list[str]:
    """Tags of `release_repo`, newest first as GitHub orders them. Empty on any
    failure — the panel then only accepts a typed tag."""
    now = time.monotonic()
    if now - _cache["at"] < CACHE_S:
        return list(_cache["tags"])
    repo = settings().release_repo
    tags: list[str] = []
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/tags?per_page=50",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "oceankind-backend/2.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            tags = [t["name"] for t in json.loads(resp.read()) if TAG_RE.match(str(t.get("name", "")))]
    except Exception as exc:                                    # noqa: BLE001
        log.info("could not list tags for %s: %s", repo, exc)
    _cache.update(at=now, tags=tags)
    return list(tags)


def fleet_default(db: Session) -> Optional[str]:
    row = db.exec(select(FleetRelease)).first()
    return row.release if row else None


def set_fleet_default(db: Session, release: Optional[str]) -> Optional[str]:
    row = db.exec(select(FleetRelease)).first()
    if row is None:
        row = FleetRelease()
    row.release = release
    row.updated_utc = datetime.now(timezone.utc)
    db.add(row)
    db.commit()
    return row.release
