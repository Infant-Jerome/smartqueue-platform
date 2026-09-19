"""Notification persistence model (N2-Persist, SmartQueue Phase 5B).

Table decision: a DB table IS justified -- in-memory does NOT suffice.

Why persistence is required:
- Retry state (``attempts``/``status``) must survive process restarts;
  an in-memory dedupe set loses it, turning every restart into either
  duplicate sends or silently dropped notifications.
- Idempotency (``type`` + ``appointment`` + ``channel`` or event id) must
  be enforced across restarts and across workers; only a DB UNIQUE
  constraint does that.
- Notifications are in-app only (see problem statement), so the inbox
  itself is a durable read model -- it cannot live in process memory.
- Audit (PENDING/SENT/FAILED + safe error + sent_at) is required to
  isolate provider failures without losing the record.

Consumer contract (for the N1 dispatcher; enforced by callers, not here):
- Post-commit only: consume ``app.services.queue_events.subscribe``;
  never create/send before the booking/queue transaction commits.
- No new bus: ``queue_events.subscribe`` is the sole feed.
- Idempotency: compute ``idempotency_key`` via ``build_idempotency_key``
  and rely on ``uq_notifications_idempotency_key`` (concurrent duplicate
  inserts raise IntegrityError -> treat as already-queued, never retry
  blindly).
- Bounded retry: ``attempts`` + ``MAX_ATTEMPTS`` (default 3); never loop
  infinitely. ``can_retry`` encodes the bound.
- Provider failure isolation: the dispatcher MUST catch every provider
  exception, store a truncated safe message via ``truncate_error`` (never
  secrets/tokens/PII beyond ids), mark FAILED, and NEVER raise into REST.

This module performs no I/O, holds no Session, and imports nothing from
services/providers/templates/ws (no cycles, no business logic).
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.db.base import Base

# --- Vocabulary ----------------------------------------------------------
STATUS_PENDING = "PENDING"
STATUS_SENT = "SENT"
STATUS_FAILED = "FAILED"
NOTIFICATION_STATUSES = (STATUS_PENDING, STATUS_SENT, STATUS_FAILED)

CHANNEL_INAPP = "inapp"

# Bounded retry: dispatcher must stop at this many attempts (no infinite).
MAX_ATTEMPTS = 3

# Error column is a safe, truncated human message -- never secrets/tokens.
MAX_ERROR_CHARS = 500


def build_idempotency_key(
    *,
    notification_type: str,
    channel: str = CHANNEL_INAPP,
    appointment_id: int | None = None,
    event_id: str | None = None,
) -> str:
    """Build the dedupe key: ``type+appointment+channel`` or a raw event id.

    When the queue event already carries a stable id, pass it as
    ``event_id`` (used verbatim, namespaced). Otherwise the key is
    ``"<type>:<appointment_id>:<channel>"`` so re-delivery of the same
    queue transition for the same appointment/channel collapses to one row
    via ``uq_notifications_idempotency_key``.
    """
    if event_id:
        return f"event:{event_id}"
    return f"{notification_type}:{appointment_id}:{channel}"


def truncate_error(message: object) -> str | None:
    """Return a safe, bounded error string (None when empty).

    Callers must strip secrets/tokens BEFORE calling; this only bounds
    length so provider tracebacks can never overflow the column.
    """
    if message is None:
        return None
    text = str(message).strip()
    if not text:
        return None
    if len(text) > MAX_ERROR_CHARS:
        return text[:MAX_ERROR_CHARS]
    return text


class Notification(Base):
    """Durable outbox/inbox row for one user notification."""

    __tablename__ = "notifications"

    notification_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    appointment_id = Column(
        Integer,
        ForeignKey("appointments.appointment_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    queue_id = Column(
        Integer,
        ForeignKey("queue.queue_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    channel = Column(String(20), nullable=False, default=CHANNEL_INAPP, index=True)
    # DB column is literally ``type`` (spec); the attribute is renamed to
    # avoid shadowing the Python builtin.
    notification_type = Column("type", String(40), nullable=False, index=True)
    status = Column(String(10), nullable=False, default=STATUS_PENDING, index=True)
    template_ref = Column(String(100), nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)
    idempotency_key = Column(String(255), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'SENT', 'FAILED')",
            name="ck_notifications_status_allowed",
        ),
        CheckConstraint("attempts >= 0", name="ck_notifications_attempts_non_negative"),
        UniqueConstraint("idempotency_key", name="uq_notifications_idempotency_key"),
        Index("ix_notifications_status_created", "status", "created_at"),
        Index("ix_notifications_type_channel", "type", "channel"),
    )

    # NOTE: FK constraints only, no ORM relationships. The owning sides
    # (User/Appointment/Queue) are untouched by design, and relationship()
    # strings would fail mapper configuration on isolated import
    # (``import app.notifications.models`` without ``app.models``).
    # Consumers join explicitly by id.

    @property
    def can_retry(self) -> bool:
        """True while the bounded-retry budget remains."""
        return (self.attempts or 0) < MAX_ATTEMPTS

    def __repr__(self) -> str:
        return (
            f"<Notification id={self.notification_id} "
            f"type={self.notification_type!r} status={self.status}>"
        )
