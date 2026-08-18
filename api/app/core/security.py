"""Passwords, sessions and the permission gate. All ours, no identity provider (R-1.4)."""
from datetime import datetime, timedelta, timezone
from typing import Optional
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from itsdangerous import TimestampSigner, BadSignature, SignatureExpired
from fastapi import Depends, HTTPException, Request, status
from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import get_session
from app.core.models import User, SiteAccess

_ph = PasswordHasher()
COOKIE = "oceankind_session"


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, pw)
    except VerifyMismatchError:
        return False


def issue_session(user_id: int) -> str:
    return TimestampSigner(settings().session_secret).sign(str(user_id)).decode()


def read_session(token: str) -> Optional[int]:
    try:
        raw = TimestampSigner(settings().session_secret).unsign(
            token, max_age=settings().session_hours * 3600)
        return int(raw)
    except (BadSignature, SignatureExpired, ValueError):
        return None


def current_user(request: Request, db: Session = Depends(get_session)) -> User:
    """Every data route depends on this. No token, no data (R-2.1)."""
    token = request.cookies.get(COOKIE)
    uid = read_session(token) if token else None
    if uid is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
    user = db.get(User, uid)
    if not user or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "administrator only")
    return user


def allowed_sites(user: User, db: Session) -> list[str]:
    if user.role == "admin":
        return []          # empty means unrestricted; callers check role first
    return list(db.exec(select(SiteAccess.site_id).where(SiteAccess.user_id == user.id)))


def assert_site_allowed(site_id: str, user: User, db: Session) -> None:
    """Guessing a URL must not work (R-3.4). Called by every site-scoped route."""
    if user.role == "admin":
        return
    if site_id not in allowed_sites(user, db):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no access to this site")
