"""Safe per-type message templates (N1-Core, Phase 5B).

Only ``{first_name}``, ``{position}`` and ``{wait_minutes}`` variables are
supported. No PII beyond first name + queue position is ever rendered.
Rendering never raises: unknown/missing values degrade to "".
"""

import logging
from typing import Optional

from app.notifications.preferences import NotificationType

logger = logging.getLogger(__name__)

# (subject, body). Bodies use only first_name / position / wait_minutes.
TEMPLATES: dict[str, tuple[str, str]] = {
    NotificationType.APPOINTMENT_BOOKED.value: (
        "Appointment booked",
        "Hi {first_name}, Your appointment has been booked successfully.",
    ),
    NotificationType.APPOINTMENT_CANCELLED.value: (
        "Appointment cancelled",
        "Hi {first_name}, your appointment has been cancelled.",
    ),
    NotificationType.QUEUE_JOINED.value: (
        "You joined the queue",
        "Hi {first_name}, you have joined the queue. Your position is {position}.",
    ),
    NotificationType.QUEUE_APPROACHING.value: (
        "Your turn is approaching",
        "Hi {first_name}, you are approaching the front of the queue. "
        "Position {position}, estimated wait {wait_minutes} minutes.",
    ),
    NotificationType.TURN_NOW.value: (
        "It's your turn",
        "Hi {first_name}, It's your turn now.",
    ),
    NotificationType.APPOINTMENT_COMPLETED.value: (
        "Appointment completed",
        "Hi {first_name}, your appointment has been completed. Thank you!",
    ),
}


def render(
    notif_type: object,
    *,
    first_name: str = "",
    position: Optional[int] = None,
    wait_minutes: Optional[int] = None,
) -> tuple[str, str]:
    """Render (subject, body) for a type. Never raises, never leaks PII."""
    key = getattr(notif_type, "value", notif_type)
    key = str(key or "").strip().lower()
    subject, body = TEMPLATES.get(key, ("Notification", "Hi {first_name}, you have a queue update."))
    safe_name = str(first_name or "").strip().split(" ")[0][:50]
    try:
        pos = "" if position is None else str(int(position))
    except (TypeError, ValueError):
        pos = ""
    try:
        wait = "" if wait_minutes is None else str(int(wait_minutes))
    except (TypeError, ValueError):
        wait = ""
    try:
        return subject, body.format(first_name=safe_name, position=pos, wait_minutes=wait)
    except Exception:
        logger.debug("templates: render fallback for type=%s", key)
        return subject, "Hi, you have a queue update."
