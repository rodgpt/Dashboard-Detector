from sqlmodel import SQLModel, Session, create_engine, select
from app.core.config import settings

_engine = None


def engine():
    global _engine
    if _engine is None:
        url = settings().db_url
        _engine = create_engine(url, connect_args={"check_same_thread": False}
                                if url.startswith("sqlite") else {})
    return _engine


def init_db() -> None:
    """Create tables and, on a fresh deployment, the first administrator (R-3.5)."""
    from app.core.models import User
    from app.core.security import hash_password
    SQLModel.metadata.create_all(engine())

    s = settings()
    if not (s.bootstrap_admin_email and s.bootstrap_admin_password):
        return
    # The login route validates emails, so an address that fails validation here
    # (e.g. admin@x.local) would create an administrator that can never log in.
    # Refuse to start rather than bootstrap a dead account (R-4.3 spirit).
    from pydantic import TypeAdapter, EmailStr, ValidationError
    try:
        TypeAdapter(EmailStr).validate_python(s.bootstrap_admin_email)
    except ValidationError:
        raise RuntimeError(
            "OCEANKIND_BOOTSTRAP_ADMIN_EMAIL is not a valid login email; "
            "use a real-format address (reserved domains like .local are rejected)")
    if len(s.bootstrap_admin_password) < 12:
        raise RuntimeError("OCEANKIND_BOOTSTRAP_ADMIN_PASSWORD must be at least 12 characters")
    with Session(engine()) as db:
        if db.exec(select(User)).first():
            return                       # already bootstrapped; do nothing
        db.add(User(email=s.bootstrap_admin_email.lower(),
                    password_hash=hash_password(s.bootstrap_admin_password),
                    role="admin"))
        db.commit()


def get_session():
    with Session(engine()) as s:
        yield s
