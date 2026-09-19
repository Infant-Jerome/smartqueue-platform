"""Queue WebSocket event envelopes (SmartQueue Phase 5A, WS1-Infra).

Every server-push message is ``{"event": <name>, "data": <payload>}`` where
``data`` carries ONLY the safe queue fields:

queue_id, appointment_id, barber_id, salon_id, queue_position, status,
current_serving, estimated_wait / estimated_wait_minutes, updated_at.

Never include: password / password_hash, JWT/token, phone, email, names or
any other PII. Customer-scoped snapshots additionally strip other
customers' ``appointment_id`` values (see ``api.v1.queue_ws``).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

QUEUE_UPDATED = "queue.updated"
QUEUE_CREATED = "queue.created"
SERVING = "queue.serving"
COMPLETED = "queue.completed"
SKIPPED = "queue.skipped"
CANCELLED = "queue.cancelled"
POSITION_CHANGED = "queue.position_changed"

QUEUE_EVENTS: tuple[str, ...] = (
    QUEUE_UPDATED,
    QUEUE_CREATED,
    SERVING,
    COMPLETED,
    SKIPPED,
    CANCELLED,
    POSITION_CHANGED,
)

_SAFE_KEYS = frozenset(
    {
        "queue_id",
        "appointment_id",
        "barber_id",
        "salon_id",
        "queue_position",
        "status",
        "current_serving",
        "currently_serving",
        "estimated_wait",
        "estimated_wait_minutes",
        "people_ahead",
        "my_position",
        "my_status",
        "my_queue_id",
        "has_queue",
        "scope",
        "entries",
        "updated_at",
        "event_version",
        # Phase 5C (S2-Integrate): SAWTE confidence for the wait estimate.
        # Allowlisted ONLY (no other new keys); forwarded verbatim.
        "confidence",
    }
)


def _iso(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def sanitize_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Strip any non-allowlisted key; normalize datetimes to ISO strings."""
    return {k: _iso(v) for k, v in (data or {}).items() if k in _SAFE_KEYS}


def build_event(event: str, data: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Build a ``{event, data}`` envelope (data sanitized)."""
    if event not in QUEUE_EVENTS:
        raise ValueError(f"Unknown queue event '{event}'")
    return {"event": event, "data": sanitize_payload(data or {})}


def queue_updated(payload: dict[str, Any]) -> dict[str, Any]:
    return build_event(QUEUE_UPDATED, payload)


def created(payload: dict[str, Any]) -> dict[str, Any]:
    return build_event(QUEUE_CREATED, payload)


def serving(payload: dict[str, Any]) -> dict[str, Any]:
    return build_event(SERVING, payload)


def completed(payload: dict[str, Any]) -> dict[str, Any]:
    return build_event(COMPLETED, payload)


def skipped(payload: dict[str, Any]) -> dict[str, Any]:
    return build_event(SKIPPED, payload)


def cancelled(payload: dict[str, Any]) -> dict[str, Any]:
    return build_event(CANCELLED, payload)


def position_changed(payload: dict[str, Any]) -> dict[str, Any]:
    return build_event(POSITION_CHANGED, payload)


def entry_payload(
    *,
    queue_id: int,
    appointment_id: int,
    barber_id: int,
    salon_id: Optional[int],
    queue_position: int,
    status: str,
    estimated_wait_minutes: Optional[int] = None,
    current_serving: Optional[int] = None,
    updated_at: Any = None,
    confidence: Any = None,
) -> dict[str, Any]:
    """Sanitized per-entry payload for staff/barber full snapshots and pushes."""
    return sanitize_payload(
        {
            "queue_id": queue_id,
            "appointment_id": appointment_id,
            "barber_id": barber_id,
            "salon_id": salon_id,
            "queue_position": queue_position,
            "status": status,
            "estimated_wait": estimated_wait_minutes,
            "estimated_wait_minutes": estimated_wait_minutes,
            "current_serving": current_serving,
            "updated_at": _iso(updated_at),
            # SAWTE confidence (verbatim; dropped when None by callers that
            # do not pass it -- sanitize keeps the allowlisted key as-is).
            "confidence": confidence,
        }
    )
