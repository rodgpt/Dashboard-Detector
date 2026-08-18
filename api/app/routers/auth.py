"""login / logout / me. Ours, not a provider's (R-2)."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr
from sqlmodel import Session, select

from app.core.db import get_session
from app.core.models import User
from app.core.security import (COOKIE, current_user, hash_password, issue_session,
                               verify_password, allowed_sites)
from app.core import ratelimit
from app.core.config import settings

router = APIRouter()


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class Ok(BaseModel):
    ok: bool


class Me(BaseModel):
    email: str
    role: str
    sites: list[str]


@router.post("/login", response_model=Ok)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_session)):
    key = f"{request.client.host}:{body.email.lower()}"
    if ratelimit.too_many(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many attempts, wait a few minutes")

    user = db.exec(select(User).where(User.email == body.email.lower())).first()
    # same error and same work either way, so the response cannot enumerate accounts
    if not user or not user.active or not verify_password(body.password, user.password_hash):
        ratelimit.record_failure(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")

    ratelimit.clear(key)
    response.set_cookie(COOKIE, issue_session(user.id), httponly=True, samesite="lax",
                        secure=settings().cookie_secure, max_age=settings().session_hours * 3600)
    return {"ok": True}


@router.post("/logout", response_model=Ok)
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"ok": True}


@router.get("/me", response_model=Me)
def me(user: User = Depends(current_user), db: Session = Depends(get_session)):
    sites = allowed_sites(user, db)
    return Me(email=user.email, role=user.role, sites=sites)
