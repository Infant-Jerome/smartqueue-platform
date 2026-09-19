"""N2-Persist notification persistence package (SmartQueue Phase 5B).

Owns ONLY the durable Notification record. Providers, templates, WS
fan-out, and dispatch/business logic belong to other workstreams and are
never imported here (this package has zero dependencies beyond
SQLAlchemy and the canonical Base).
"""

from app.notifications.models import (
    CHANNEL_INAPP,
    MAX_ATTEMPTS,
    MAX_ERROR_CHARS,
    NOTIFICATION_STATUSES,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_SENT,
    Notification,
    build_idempotency_key,
    truncate_error,
)

__all__ = [
    "CHANNEL_INAPP",
    "MAX_ATTEMPTS",
    "MAX_ERROR_CHARS",
    "NOTIFICATION_STATUSES",
    "STATUS_FAILED",
    "STATUS_PENDING",
    "STATUS_SENT",
    "Notification",
    "build_idempotency_key",
    "truncate_error",
]
