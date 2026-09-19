"""Backwards-compatibility shim: canonical auth lives in app.core.dependencies.

All existing routers (``from app.api.deps import get_current_user`` /
``require_role``) keep working. No logic here — import from
``app.core.dependencies`` directly in new code.
"""
from app.core.dependencies import (
    bearer_scheme,
    get_current_user,
    get_db,
    require_admin,
    require_receptionist,
    require_role,
    require_staff,
    require_staff_or_admin,
)

# Historic name used by earlier wiring; alias of the canonical bearer scheme.
security_scheme = bearer_scheme

__all__ = [
    "bearer_scheme",
    "security_scheme",
    "get_db",
    "get_current_user",
    "require_role",
    "require_admin",
    "require_staff",
    "require_staff_or_admin",
    "require_receptionist",
]
