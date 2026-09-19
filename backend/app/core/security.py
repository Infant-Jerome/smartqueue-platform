"""Security foundation (Phase 1): password hashing + JWT helpers.

Scope is intentionally narrow: hash/verify utilities, JWT create/decode, and
lightweight role stubs. Full auth flows (register/login routes, current-user
wiring) live in the API layer and Phase 2.

- Reuses the existing ``bcrypt`` (direct) choice; no downgrade to weaker
  hashes, no new passlib dependency.
- Secrets come from settings env only; never log them.
"""
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.core.config import get_settings


def _settings():
    # Lazy accessor so tests can override env before first use.
    return get_settings()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), hashed_password.encode("utf-8")
        )
    except (ValueError, TypeError):
        # Malformed hash -> treat as non-match, never raise/leak details.
        return False


# Backwards-compatible aliases (some codebases/tests use these names).
get_password_hash = hash_password
verify_hash = verify_password


def create_access_token(data: dict, expires_minutes: int | None = None) -> str:
    """Create a signed JWT. ``data`` must contain ``sub`` (user id)."""
    settings = _settings()
    to_encode: dict[str, Any] = dict(data)
    minutes = expires_minutes if expires_minutes is not None else settings.JWT_EXPIRE_MINUTES
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """Decode/verify a JWT; return payload dict or None if invalid/expired."""
    settings = _settings()
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None


def get_token_subject(token: str) -> str | None:
    """Stub helper for Phase 2: extract ``sub`` without DB access."""
    payload = decode_access_token(token)
    if not payload:
        return None
    sub = payload.get("sub")
    return str(sub) if sub is not None else None


# Valid roles in this platform (used by role dependencies).
# ``receptionist`` and ``staff`` are aliases (front-desk role); ``staff`` is
# kept for backwards compatibility with existing routers/tests.
VALID_ROLES: tuple[str, ...] = ("customer", "barber", "receptionist", "staff", "admin")


def is_valid_role(role: str) -> bool:
    try:
        return str(role).strip().lower() in VALID_ROLES
    except Exception:
        return False
