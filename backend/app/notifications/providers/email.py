"""Email provider: Mock (record, success, never real) + disabled-by-default
SMTP stub. Secrets are never logged."""

import logging
from typing import Any, Optional

from app.notifications.providers.base import NotificationProvider, Result

logger = logging.getLogger(__name__)


class MockEmailProvider(NotificationProvider):
    """Test/dev provider: records sends in-memory, always succeeds."""

    name = "email_mock"

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
        logger.debug("MockEmailProvider: recorded send to=%s", to)
        return Result(success=True, provider=self.name)


class SmtpEmailProvider(NotificationProvider):
    """Real-provider stub. Disabled unless EMAIL_ENABLED + host creds exist.

    Never logs credentials (only host/port on failures). Even when enabled
    this stub performs the smtplib send inline with a short timeout and no
    retries of its own (the service bounds retries); any error -> Result.
    """

    name = "email_smtp"

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
        if not settings.EMAIL_ENABLED:
            return Result(success=False, error="email provider disabled", provider=self.name)
        if not (settings.EMAIL_HOST and settings.EMAIL_USER and settings.EMAIL_PASS):
            # Log host only — never user/pass.
            logger.warning(
                "SmtpEmailProvider: missing credentials (host=%s)", settings.EMAIL_HOST or "unset"
            )
            return Result(success=False, error="email credentials missing", provider=self.name)
        try:
            import smtplib
            from email.mime.text import MIMEText

            msg = MIMEText(body or "")
            msg["Subject"] = subject or ""
            msg["From"] = settings.EMAIL_FROM or settings.EMAIL_USER
            msg["To"] = to
            port = int(settings.EMAIL_PORT or 587)
            with smtplib.SMTP(settings.EMAIL_HOST, port, timeout=10) as client:
                client.starttls()
                client.login(settings.EMAIL_USER, settings.EMAIL_PASS)
                client.send_message(msg)
            return Result(success=True, provider=self.name)
        except Exception as exc:
            logger.warning(
                "SmtpEmailProvider: send failed (host=%s port=%s): %s",
                settings.EMAIL_HOST,
                settings.EMAIL_PORT,
                type(exc).__name__,
            )
            return Result(success=False, error=f"email send failed: {type(exc).__name__}", provider=self.name)
