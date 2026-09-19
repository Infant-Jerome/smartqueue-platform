"""Notification fan-out service (N1-Core, Phase 5B).

``NotificationService.handle(queue_event)`` is subscribed to
``queue_events.subscribe`` (wiring only — queue/appointment business
logic is never touched). Per event it:

1. Maps the queue event type -> :class:`NotificationType`
   (``queue.updated`` only notifies when position <= APPROACHING_THRESHOLD,
   otherwise it is a silent position refresh).
2. Resolves the recipient via DB (appointment -> customer User; lazy
   imports, own short-lived session, read-only on queue/appointment/user
   rows). Falls back to explicit ``user_id``/``customer_id`` carried in
   the event (tests). Unresolvable -> skip quietly.
3. Checks :mod:`app.notifications.preferences` per channel (security
   messages bypass).
4. Applies the idempotency key (event type + appointment + channel).
5. Renders via :mod:`app.notifications.templates`, creates a record
   in the N2 durable model (graceful outbox-only fallback when the table
   is unavailable), then sends via the channel provider with bounded
   retry (max 3, no celery, no sleep).
6. Failures land as FAILED without raising — REST is never broken.

Coordination notes (N1 + N2):
- N2-Persist owns ``app.notifications.models`` (durable ``Notification``
  row, ``build_idempotency_key``, ``truncate_error``, ``MAX_ATTEMPTS``).
  This module is N2's dispatcher/consumer and follows its contract:
  post-commit consume via ``queue_events.subscribe`` only, idempotency
  via ``build_idempotency_key`` + the DB UNIQUE constraint, bounded
  retry, provider-failure isolation (safe truncated errors, never raise).
- Channel/type vocabulary (``Channel`` EMAIL/PUSH/SMS,
  ``NotificationType``) stays N1-owned in
  :mod:`app.notifications.preferences` (the prefs coordination point).

No queue mutation: this module only reads Queue/Appointment/User and
writes notification records/outbox.
"""

import logging
from datetime import datetime
from typing import Any, Optional

from app.notifications.preferences import (
    Channel,
    NotificationStatus,
    NotificationType,
    is_channel_enabled,
)
from app.notifications.providers import get_provider
from app.notifications.templates import render

logger = logging.getLogger(__name__)

# Re-exported vocabulary (also satisfies the cross-workstream contract pin:
# ``service.NotificationStatus`` must exist; delivery never depends on it).
__all__ = [
    "Channel",
    "NotificationType",
    "NotificationStatus",
    "NotificationService",
    "service",
    "OUTBOX",
    "EVENT_TO_TYPE",
    "MAX_ATTEMPTS",
    "subscribe_notifications",
    "unsubscribe_notifications",
    "clear_outbox",
]
_ = NotificationStatus.PENDING

try:  # N2-Persist durable vocabulary (single source of truth when present).
    from app.notifications.models import (
        STATUS_FAILED,
        STATUS_PENDING,
        STATUS_SENT,
        build_idempotency_key,
        truncate_error,
    )
except Exception:  # pragma: no cover - N2 model always present in practice.

    STATUS_PENDING = "PENDING"
    STATUS_SENT = "SENT"
    STATUS_FAILED = "FAILED"

    def build_idempotency_key(
        *,
        notification_type: str,
        channel: str = "email",
        appointment_id: Optional[int] = None,
        event_id: Optional[str] = None,
    ) -> str:
        if event_id:
            return f"event:{event_id}"
        return f"{notification_type}:{appointment_id}:{channel}"

    def truncate_error(message: object) -> Optional[str]:
        text = str(message or "").strip()
        return text[:500] if text else None


def _max_attempts() -> int:
    try:
        from app.notifications.models import MAX_ATTEMPTS as N2_MAX

        return int(N2_MAX)
    except Exception:
        return 3


MAX_ATTEMPTS = 3

# queue event type -> notification type. queue.updated is handled
# separately (approaching-threshold gate).
EVENT_TO_TYPE: dict[str, str] = {
    "queue.created": NotificationType.QUEUE_JOINED.value,
    "queue.serving": NotificationType.TURN_NOW.value,
    "queue.completed": NotificationType.APPOINTMENT_COMPLETED.value,
    "queue.cancelled": NotificationType.APPOINTMENT_CANCELLED.value,
    # queue.skipped (no_show) and queue.updated: see _map_event().
}

# appointment-domain events (no publisher yet; mapped for forward-compat).
APPT_EVENT_TO_TYPE: dict[str, str] = {
    "appointment.booked": NotificationType.APPOINTMENT_BOOKED.value,
    "appointment_booked": NotificationType.APPOINTMENT_BOOKED.value,
    "appointment.cancelled": NotificationType.APPOINTMENT_CANCELLED.value,
    "appointment.completed": NotificationType.APPOINTMENT_COMPLETED.value,
}

# In-memory outbox mirror of every record this process creates (tests +
# fallback when the notifications table is unavailable).
OUTBOX: list[dict] = []

# Idempotency keys already processed by this process.
_SEEN_KEYS: set[str] = set()


def _notification_model():
    """Return N2's durable model, or None when unavailable (outbox only)."""
    try:
        from app.notifications.models import Notification as N2Model

        return N2Model
    except Exception:
        return None


def _approaching_threshold() -> int:
    try:
        from app.core.config import get_settings

        return int(get_settings().APPROACHING_THRESHOLD or 2)
    except Exception:
        return 2


def _map_event(event: dict) -> Optional[str]:
    """Map a queue/appointment event envelope -> notification type value."""
    etype = str(event.get("type") or "").strip().lower()
    if etype in EVENT_TO_TYPE:
        return EVENT_TO_TYPE[etype]
    if etype in APPT_EVENT_TO_TYPE:
        return APPT_EVENT_TO_TYPE[etype]
    if etype in ("queue.updated", "queue_updated"):
        try:
            pos = event.get("data", {}).get("queue_position")
            pos = int(pos) if pos is not None else None
        except (TypeError, ValueError):
            pos = None
        if pos is not None and pos <= _approaching_threshold():
            return NotificationType.QUEUE_APPROACHING.value
        return None
    if etype in ("queue.skipped", "queue_skipped"):
        return None  # no_show: no customer message by default.
    return None


def _resolve_recipient(event: dict) -> Optional[dict]:
    """Resolve {user_id, first_name, email, phone, appointment_id}.

    Lazy imports, own session, read-only. Never raises.
    """
    data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}
    appointment_id = data.get("appointment_id", event.get("appointment_id"))
    queue_id = data.get("queue_id", event.get("queue_id"))
    explicit_uid = data.get("user_id", data.get("customer_id", event.get("user_id")))
    position = data.get("queue_position", event.get("queue_position"))
    wait = data.get("estimated_wait_minutes", event.get("estimated_wait_minutes"))

    session = None
    try:
        if appointment_id is not None:
            from app.db.database import SessionLocal
            from app.models.appointment import Appointment
            from app.models.user import User

            session = SessionLocal()
            appt = (
                session.query(Appointment)
                .filter(Appointment.appointment_id == int(appointment_id))
                .first()
            )
            if appt is not None:
                user = (
                    session.query(User).filter(User.user_id == appt.customer_id).first()
                )
                if user is not None:
                    name = str(getattr(user, "name", "") or "")
                    return {
                        "user_id": user.user_id,
                        "first_name": name.strip().split(" ")[0] if name.strip() else "",
                        "email": getattr(user, "email", "") or "",
                        "phone": getattr(user, "phone", "") or "",
                        "appointment_id": appointment_id,
                        "queue_id": queue_id,
                        "position": position,
                        "wait_minutes": wait,
                    }
    except Exception:
        logger.debug("notifications: DB recipient lookup failed", exc_info=False)
    finally:
        try:
            if session is not None:
                session.close()
        except Exception:
            pass

    # Fallback: explicit recipient carried in the event (tests / callers).
    if explicit_uid is not None:
        try:
            uid = int(explicit_uid)
        except (TypeError, ValueError):
            return None
        return {
            "user_id": uid,
            "first_name": str(event.get("first_name", "") or data.get("first_name", "")),
            "email": str(event.get("email", "") or data.get("email", "")),
            "phone": str(event.get("phone", "") or data.get("phone", "")),
            "appointment_id": appointment_id,
            "queue_id": queue_id,
            "position": position,
            "wait_minutes": wait,
        }
    return None


def _address_for(channel_value: str, recipient: dict) -> str:
    if channel_value == Channel.EMAIL.value:
        return str(recipient.get("email") or "")
    if channel_value == Channel.SMS.value:
        return str(recipient.get("phone") or "")
    # Push targets the user identity (device fan-out is gateway-side).
    return str(recipient.get("user_id") or "")


def _persist_record(record: dict) -> Optional[int]:
    """Best-effort DB persist using N2's durable columns. Never raises.

    Concurrent duplicates hit ``uq_notifications_idempotency_key``: the
    IntegrityError is treated as already-queued (existing row id returned,
    no blind retry).
    """
    model = _notification_model()
    if model is None:
        return None
    try:
        from sqlalchemy.exc import IntegrityError

        from app.db.database import SessionLocal

        session = SessionLocal()
        try:
            row = model(
                user_id=record.get("user_id"),
                appointment_id=record.get("appointment_id"),
                queue_id=record.get("queue_id"),
                channel=record.get("channel"),
                notification_type=record.get("type"),
                status=STATUS_PENDING,
                template_ref=record.get("type"),
                attempts=0,
                error=None,
                idempotency_key=record.get("idempotency_key"),
            )
            session.add(row)
            session.commit()
            try:
                return int(getattr(row, "notification_id", 0) or 0) or None
            except (TypeError, ValueError):
                return None
        except IntegrityError:
            try:
                session.rollback()
                existing = (
                    session.query(model)
                    .filter(model.idempotency_key == record.get("idempotency_key"))
                    .first()
                )
                if existing is not None:
                    return getattr(existing, "notification_id", None)
            except Exception:
                pass
            return None
        finally:
            try:
                session.close()
            except Exception:
                pass
    except Exception:
        logger.debug("notifications: DB persist failed; outbox only", exc_info=False)
        return None


def _update_record_status(
    idempotency_key: str,
    status: str,
    attempts: int,
    error: Optional[str],
    sent: bool = False,
) -> None:
    """Best-effort status update on the persisted row. Never raises."""
    model = _notification_model()
    if model is None:
        return
    try:
        from app.db.database import SessionLocal

        session = SessionLocal()
        try:
            row = (
                session.query(model)
                .filter(model.idempotency_key == idempotency_key)
                .first()
            )
            if row is not None:
                row.status = status
                row.attempts = attempts
                row.error = truncate_error(error)
                if sent:
                    row.sent_at = datetime.utcnow()
                session.commit()
        finally:
            try:
                session.close()
            except Exception:
                pass
    except Exception:
        logger.debug("notifications: status update failed (ignored)", exc_info=False)


class NotificationService:
    """Event-driven fan-out. One shared instance is subscribed at startup."""

    def handle(self, event: Any) -> list[dict]:
        """Handle one queue event envelope. Never raises, never mutates queue."""
        try:
            if not isinstance(event, dict):
                return []
            try:
                from app.core.config import get_settings

                if not bool(get_settings().NOTIFS_ENABLED):
                    return []
            except Exception:
                pass

            notif_type = _map_event(event)
            if notif_type is None:
                return []

            recipient = _resolve_recipient(event)
            if recipient is None:
                logger.debug("notifications: no recipient for event %r", event.get("type"))
                return []

            data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}
            try:
                position = data.get("queue_position")
                position = int(position) if position is not None else recipient.get("position")
                if position is not None:
                    position = int(position)
            except (TypeError, ValueError):
                position = None
            try:
                wait = data.get("estimated_wait_minutes")
                wait = int(wait) if wait is not None else recipient.get("wait_minutes")
                if wait is not None:
                    wait = int(wait)
            except (TypeError, ValueError):
                wait = None

            subject, body = render(
                notif_type,
                first_name=recipient.get("first_name", ""),
                position=position,
                wait_minutes=wait,
            )

            results: list[dict] = []
            max_attempts = _max_attempts()
            for channel in (Channel.EMAIL, Channel.PUSH, Channel.SMS):
                cval = channel.value
                try:
                    if not is_channel_enabled(recipient.get("user_id"), cval, notif_type):
                        continue
                    key = build_idempotency_key(
                        notification_type=notif_type,
                        channel=cval,
                        appointment_id=recipient.get("appointment_id"),
                    )
                    if key in _SEEN_KEYS:
                        continue
                    _SEEN_KEYS.add(key)

                    record: dict = {
                        "notification_id": None,
                        "user_id": recipient.get("user_id"),
                        "appointment_id": recipient.get("appointment_id"),
                        "queue_id": recipient.get("queue_id"),
                        "channel": cval,
                        "type": notif_type,
                        "subject": subject,
                        "body": body,
                        "status": STATUS_PENDING,
                        "idempotency_key": key,
                        "attempts": 0,
                        "last_error": None,
                        "created_at": datetime.utcnow().isoformat(),
                    }
                    OUTBOX.append(record)

                    db_id = _persist_record(record)
                    if db_id is not None:
                        record["notification_id"] = db_id

                    to = _address_for(cval, recipient)
                    if not to:
                        record["status"] = STATUS_FAILED
                        record["last_error"] = f"missing address for {cval}"
                        _update_record_status(key, record["status"], 0, record["last_error"])
                        results.append(record)
                        continue

                    provider = get_provider(cval)
                    last_error: Optional[str] = None
                    sent = False
                    attempts = 0
                    for _ in range(max_attempts):
                        attempts += 1
                        try:
                            outcome = provider.send(
                                to=to,
                                subject=subject,
                                body=body,
                                metadata={
                                    "user_id": recipient.get("user_id"),
                                    "appointment_id": recipient.get("appointment_id"),
                                    "type": notif_type,
                                },
                            )
                        except Exception as exc:  # provider must not break us
                            logger.warning("notifications: provider raised (%s)", type(exc).__name__)
                            last_error = f"provider error: {type(exc).__name__}"
                            continue
                        if outcome is not None and bool(getattr(outcome, "success", False)):
                            sent = True
                            last_error = None
                            break
                        try:
                            last_error = str(getattr(outcome, "error", None) or "send failed")
                        except Exception:
                            last_error = "send failed"
                    record["attempts"] = attempts
                    record["last_error"] = last_error
                    record["status"] = STATUS_SENT if sent else STATUS_FAILED
                    _update_record_status(key, record["status"], attempts, last_error, sent=sent)
                    results.append(record)
                except Exception:
                    logger.exception("notifications: channel %s failed (ignored)", cval)
                    continue
            return results
        except Exception:
            logger.exception("notifications: handle failed (ignored)")
            return []


service = NotificationService()

_SUBSCRIBED = False


def subscribe_notifications() -> NotificationService:
    """Subscribe the shared service to queue events (idempotent)."""
    global _SUBSCRIBED
    try:
        from app.services import queue_events

        if not _SUBSCRIBED:
            queue_events.subscribe(service.handle)
            _SUBSCRIBED = True
    except Exception:
        logger.debug("notifications: subscribe failed (ignored)", exc_info=False)
    return service


def unsubscribe_notifications() -> None:
    """Detach the shared service from queue events (idempotent)."""
    global _SUBSCRIBED
    try:
        from app.services import queue_events

        queue_events.unsubscribe(service.handle)
    except Exception:
        pass
    _SUBSCRIBED = False


def clear_outbox() -> None:
    """Clear in-memory outbox + idempotency keys (tests only)."""
    OUTBOX.clear()
    _SEEN_KEYS.clear()
