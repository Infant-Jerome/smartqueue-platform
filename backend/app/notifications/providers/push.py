"""Push provider: Mock (record, success, never real) + disabled-by-default stub."""

import logging
from typing import Any, Optional

from app.notifications.providers.base import NotificationProvider, Result

logger = logging.getLogger(__name__)


class MockPushProvider(NotificationProvider):
    """Test/dev provider: records sends in-memory, always succeeds."""

    name = "push_mock"

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
        logger.debug("MockPushProvider: recorded send to=%s", to)
        return Result(success=True, provider=self.name)


class HttpPushProvider(NotificationProvider):
    """Real-provider stub. Disabled unless PUSH_ENABLED + host creds exist.

    Never logs secrets (only host on failures). When enabled this stub
    performs NO external network call yet — it returns a stubbed success so
    wiring can be verified without a push gateway. Replace the stubbed
    branch with the gateway call when credentials are provisioned.
    """

    name = "push_http"

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
        if not settings.PUSH_ENABLED:
            return Result(success=False, error="push provider disabled", provider=self.name)
        if not (settings.PUSH_HOST and settings.PUSH_USER and settings.PUSH_PASS):
            logger.warning(
                "HttpPushProvider: missing credentials (host=%s)", settings.PUSH_HOST or "unset"
            )
            return Result(success=False, error="push credentials missing", provider=self.name)
        logger.debug("HttpPushProvider: stubbed send (host=%s)", settings.PUSH_HOST)
        return Result(success=True, provider=self.name)
