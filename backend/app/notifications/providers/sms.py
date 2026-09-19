"""SMS provider: Mock (record, success, never real) + disabled-by-default stub."""

import logging
from typing import Any, Optional

from app.notifications.providers.base import NotificationProvider, Result

logger = logging.getLogger(__name__)


class MockSmsProvider(NotificationProvider):
    """Test/dev provider: records sends in-memory, always succeeds."""

    name = "sms_mock"

    SENT: list[dict] = []

    @classmethod
    def clear(cls) -> None:
        cls.SENT.clear()

    def send(
        self,
        *,
        to: str,
        subject: str = "",
        body: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> Result:
        self.SENT.append(
            {"to": to, "subject": subject, "body": body, "metadata": metadata or {}}
        )
        logger.debug("MockSmsProvider: recorded send to=%s", to)
        return Result(success=True, provider=self.name)


class HttpSmsProvider(NotificationProvider):
    """Real-provider stub. Disabled unless SMS_ENABLED + host creds exist.

    Never logs secrets (only host on failures). When enabled this stub
    performs NO external network call yet — it returns a stubbed success so
    wiring can be verified without an SMS gateway.
    """

    name = "sms_http"

    def send(
        self,
        *,
        to: str,
        subject: str = "",
        body: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> Result:
        try:
            from app.core.config import get_settings

            settings = get_settings()
        except Exception as exc:
            return Result(success=False, error=f"settings unavailable: {exc}", provider=self.name)
        if not settings.SMS_ENABLED:
            return Result(success=False, error="sms provider disabled", provider=self.name)
        if not (settings.SMS_HOST and settings.SMS_USER and settings.SMS_PASS):
            logger.warning(
                "HttpSmsProvider: missing credentials (host=%s)", settings.SMS_HOST or "unset"
            )
            return Result(success=False, error="sms credentials missing", provider=self.name)
        logger.debug("HttpSmsProvider: stubbed send (host=%s)", settings.SMS_HOST)
        return Result(success=True, provider=self.name)
