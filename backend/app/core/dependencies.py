"""Canonical FastAPI auth dependencies.

``app.api.deps`` is a thin shim re-exporting this module; all logic lives
here so routers keep working with a single implementation.

No circular imports: ``User`` / ``UserRole`` are imported lazily *inside*
the dependency functions, so ``app.models.*`` never needs this module.
"""
from enum import Enum

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.database import get_db

bearer_scheme = HTTPBearer(auto_error=True)

__all__ = [
    "get_db",
    "bearer_scheme",
    "get_current_user",
    "require_role",
    "require_admin",
    "require_staff_or_admin",
    "require_staff",
    "require_receptionist",
]

_UNAUTHORIZED_HEADERS = {"WWW-Authenticate": "Bearer"}

# ``receptionist`` and ``staff`` are the same front-desk role; either value
# satisfies a guard requiring the other.
_STAFF_ALIASES = frozenset({"staff", "receptionist"})


def _normalize_role(value: object) -> str:
    if isinstance(value, Enum):
        value = value.value
    return str(value or "").strip().lower()


def _expand_role_aliases(roles: tuple[str, ...] | list[str]) -> set[str]:
    expanded: set[str] = set()
    for r in roles:
        low = _normalize_role(r)
        if not low:
            continue
        expanded.add(low)
        if low in _STAFF_ALIASES:
            expanded |= set(_STAFF_ALIASES)
    return expanded


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    """Resolve the JWT bearer token to a ``User`` row."""
    from app.core.security import decode_access_token
    from app.models.user import User

    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers=_UNAUTHORIZED_HEADERS,
        )
    sub = payload.get("sub")
    if sub is None or (isinstance(sub, str) and not sub.strip()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers=_UNAUTHORIZED_HEADERS,
        )
    try:
        uid = int(sub)
    except (TypeError, ValueError):
        # Non-integer ``sub`` must be a 401, never a 500 (see api/deps bug).
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers=_UNAUTHORIZED_HEADERS,
        )
    user = db.query(User).filter(User.user_id == uid).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers=_UNAUTHORIZED_HEADERS,
        )
    return user


def require_role(*roles: str):
    """Case-insensitive role guard: ``Depends(require_role("admin"))``.

    ``receptionist`` == ``staff`` (alias accepted on either side).
    Failures are 403 ``Insufficient permissions`` with no token details.
    """
    allowed = _expand_role_aliases(tuple(roles))

    def role_checker(current_user=Depends(get_current_user)):
        actual = _normalize_role(getattr(current_user, "role", ""))
        if actual not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return role_checker


# Convenience guards for route wiring.
require_admin = require_role("admin")
require_staff_or_admin = require_role("admin", "staff", "receptionist")
# Backwards-compat alias (historic name for the staff-level guard).
require_staff = require_staff_or_admin
require_receptionist = require_role("receptionist")
