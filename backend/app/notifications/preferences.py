"""Per-user per-channel preferences (N1-Core, Phase 5B).

N2 owns the preferences table long-term. Until then this module is the
single coordination point: an in-memory store with safe defaults
(email ON, push ON, sms OFF). ``is_channel_enabled`` is the only read
path the service uses, so N2 can back it with a table later without
changing callers.

Security/time-critical messages (``SECURITY_TYPES``) are NEVER blocked
by preferences.
"""

import enum
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class Channel(str, enum.Enum):
    """Single channel enum for all notification traffic (N1-owned)."""

    EMAIL = "email"
    PUSH = "push"
    SMS = "sms"


class NotificationType(str, enum.Enum):
    """Minimum supported notification types, Phase 5B (N1-owned)."""

    APPOINTMENT_BOOKED = "appointment_booked"
    APPOINTMENT_CANCELLED = "appointment_cancelled"
    QUEUE_JOINED = "queue_joined"
    QUEUE_APPROACHING = "queue_approaching"
    TURN_NOW = "turn_now"
    APPOINTMENT_COMPLETED = "appointment_completed"


class NotificationStatus(str, enum.Enum):
    """Delivery lifecycle (N1-owned alias; values match N2's durable statuses)."""

    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"

# Security messages bypass preference checks (always delivered).
SECURITY_TYPES = frozenset({NotificationType.TURN_NOW.value})

_DEFAULTS: dict[str, bool] = {
    Channel.EMAIL.value: True,
    Channel.PUSH.value: True,
    Channel.SMS.value: False,
}

# (user_id, channel_value) -> enabled. In-memory until N2's table lands.
_PREFS: dict[tuple[int, str], bool] = {}


def _norm_channel(channel: object) -> str:
    value = getattr(channel, "value", channel)
    return str(value or "").strip().lower()


def _norm_type(notif_type: object) -> str:
    value = getattr(notif_type, "value", notif_type)
    return str(value or "").strip().lower()


def get_preferences(user_id: int) -> dict[str, bool]:
    """Return the effective per-channel preferences for a user."""
    out: dict[str, bool] = {}
    for channel_value, default in _DEFAULTS.items():
        out[channel_value] = _PREFS.get((int(user_id), channel_value), default)
    return out


def set_preference(user_id: int, channel: object, enabled: bool) -> dict[str, bool]:
    """Set one channel toggle; returns the effective preferences."""
    key = _norm_channel(channel)
    if key not in _DEFAULTS:
        raise ValueError(f"Unknown channel: {channel!r}")
    _PREFS[(int(user_id), key)] = bool(enabled)
    return get_preferences(user_id)


def is_channel_enabled(
    user_id: Optional[int],
    channel: object,
    notif_type: object = None,
) -> bool:
    """True when a notification may be sent on this channel.

    Security types always return True (never block security messages).
    Unknown users fall back to channel defaults.
    """
    if notif_type is not None and _norm_type(notif_type) in SECURITY_TYPES:
        return True
    key = _norm_channel(channel)
    default = _DEFAULTS.get(key, False)
    if user_id is None:
        return default
    try:
        return _PREFS.get((int(user_id), key), default)
    except (TypeError, ValueError):
        logger.debug("preferences: bad user_id %r; using default", user_id)
        return default


def clear_preferences() -> None:
    """Reset in-memory toggles (tests only)."""
    _PREFS.clear()
