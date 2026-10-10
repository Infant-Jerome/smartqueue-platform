"""Email provider: Mock (record, success, never real) + disabled-by-default
SMTP stub. Secrets are never logged."""

import logging
from typing import Any, Optional

from app.notifications.providers.base import NotificationProvider, Result

logger = logging.getLogger(__name__)


def _safe_detail(exc: BaseException, limit: int = 200) -> str:
    """One-line exception detail safe for logs.

    ``smtplib``/``socket``/``ssl`` errors carry errno + address info only;
    the password is passed to ``login()`` but never echoed in exceptions.
    Truncated to keep logs tidy. Never call with OTPs/tokens/passwords.
    """
    try:
        text = str(exc).strip().replace("\n", " ").replace("\r", " ")
    except Exception:
        text = ""
    return (text or type(exc).__name__)[:limit]


def _dns_families(host: str, port: int) -> str:
    """Resolved address mix, e.g. ``v4:2/v6:1`` (diagnostic only).

    Never raises. DNS names/addresses are not secrets. When the connect
    stage later fails, this tells whether DNS worked and which families
    were even candidates (e.g. ``dns-fail:gaierror`` vs ``v4:0/v6:2``
    vs ``v4:3/v6:0`` followed by TCP refusal).
    """
    try:
        import socket as _socket

        infos = _socket.getaddrinfo(host, port, type=_socket.SOCK_STREAM)
        v4 = sum(1 for i in infos if i[0] == _socket.AF_INET)
        v6 = sum(1 for i in infos if i[0] == _socket.AF_INET6)
        return f"v4:{v4}/v6:{v6}"
    except Exception as exc:  # DNS resolution itself failed
        return f"dns-fail:{type(exc).__name__}"


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
            # Staged so Render logs reveal WHERE it breaks: connect (DNS/TCP),
            # starttls (TLS handshake), login (SMTP auth), or send (submission).
            # Port 587 + STARTTLS is the correct explicit-TLS pattern.
            # NOTE (Render free tier): platform blocks outbound SMTP ports
            # 25/465/587, surfacing as OSError errno 101 at stage=connect.
            # No code change can lift a platform egress block; the dns=
            # field below proves it at runtime (DNS ok + TCP refused vs
            # dns-fail).
            stage = "connect"
            dns = "unknown"
            dns = _dns_families(settings.EMAIL_HOST, port)
            with smtplib.SMTP(settings.EMAIL_HOST, port, timeout=10) as client:
                stage = "starttls"
                client.starttls()
                stage = "login"
                client.login(settings.EMAIL_USER, settings.EMAIL_PASS)
                stage = "send"
                client.send_message(msg)
            return Result(success=True, provider=self.name)
        except Exception as exc:
            # Host/port/type/detail only: never user/pass/OTP/token content.
            logger.warning(
                "SmtpEmailProvider: send failed at stage=%s dns=%s (host=%s port=%s): %s: %s",
                stage,
                dns,
                settings.EMAIL_HOST,
                settings.EMAIL_PORT,
                type(exc).__name__,
                _safe_detail(exc),
            )
            return Result(success=False, error=f"email send failed: {type(exc).__name__}", provider=self.name)
