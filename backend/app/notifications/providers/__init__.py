"""Channel providers (N1-Core, Phase 5B).

Each channel exposes a Mock (record + success, never real) and a real
stub that stays disabled unless ``{CH}_ENABLED`` + credentials are set
via env. Channel-disabled (the default) routes to the Mock so delivery
is observable in dev/tests without any external call.
"""

from app.notifications.preferences import Channel
from app.notifications.providers.base import NotificationProvider, Result
from app.notifications.providers.email import MockEmailProvider, SmtpEmailProvider
from app.notifications.providers.push import HttpPushProvider, MockPushProvider
from app.notifications.providers.sms import HttpSmsProvider, MockSmsProvider

__all__ = [
    "NotificationProvider",
    "Result",
    "MockEmailProvider",
    "SmtpEmailProvider",
    "MockPushProvider",
    "HttpPushProvider",
    "MockSmsProvider",
    "HttpSmsProvider",
    "get_provider",
    "clear_mock_sends",
]


def get_provider(channel: object) -> NotificationProvider:
    """Return the active provider for a channel.

    Real stub only when ``{CH}_ENABLED`` is true; otherwise the Mock.
    Never raises: falls back to the Mock on any settings error.
    """
    value = getattr(channel, "value", channel)
    key = str(value or "").strip().lower()
    try:
        from app.core.config import get_settings

        settings = get_settings()
    except Exception:
        settings = None
    enabled = False
    if settings is not None:
        try:
            if key == Channel.EMAIL.value:
                enabled = bool(settings.EMAIL_ENABLED)
            elif key == Channel.PUSH.value:
                enabled = bool(settings.PUSH_ENABLED)
            elif key == Channel.SMS.value:
                enabled = bool(settings.SMS_ENABLED)
        except Exception:
            enabled = False
    if key == Channel.EMAIL.value:
        return SmtpEmailProvider() if enabled else MockEmailProvider()
    if key == Channel.PUSH.value:
        return HttpPushProvider() if enabled else MockPushProvider()
    if key == Channel.SMS.value:
        return HttpSmsProvider() if enabled else MockSmsProvider()
    return MockEmailProvider()


def clear_mock_sends() -> None:
    """Clear all Mock provider recordings (tests only)."""
    MockEmailProvider.clear()
    MockPushProvider.clear()
    MockSmsProvider.clear()
