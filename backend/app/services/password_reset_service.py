"""Password-reset service (Forgot Password + Email OTP + reset token).

Flow: forgot-password (issue HMAC-hashed OTP row + email, generic reply)
  -> verify-reset-otp (check hash/expiry/attempts, issue short-lived
  reset JWT bound to the row) -> reset-password (consume row, set hash).

Security notes:
- Raw OTPs are never persisted (HMAC-SHA256 with the JWT secret as
  pepper), never logged, never returned by the API. ``secrets`` CSPRNG
  only -- no ``random`` module anywhere.
- Reset authorization is a stateless JWT (purpose=password_reset,
  ``rid`` row binding, 15-min expiry); one-time use is enforced by the
  row's ``used_at`` marker. No second password-hashing system: reuse
  ``app.core.security.hash_password``.
- Email goes through the existing notification provider factory
  (``get_provider(Channel.EMAIL)``): Mock in dev/tests (observable via
  ``MockEmailProvider.SENT``), SMTP stub in prod when EMAIL_* env is set.
- All failures raise typed errors; routes map them to generic messages
  (no account enumeration, no detail leaks).
"""

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import create_access_token, decode_access_token, hash_password
from app.models.password_reset import (
    OTP_EXPIRY_MINUTES,
    OTP_MAX_ATTEMPTS,
    RESET_TOKEN_EXPIRY_MINUTES,
    RESEND_COOLDOWN_SECONDS,
    PasswordResetToken,
)
from app.models.user import User

logger = logging.getLogger(__name__)

RESET_PURPOSE = "password_reset"

GENERIC_FORGOT_MESSAGE = "If an account exists for this email, a verification code has been sent."


class ResetError(Exception):
    """Base class for password-reset failures (routes map to responses)."""


class EmailDeliveryError(ResetError):
    pass


class ResendCooldownError(ResetError):
    pass


class InvalidOtpError(ResetError):
    pass


class ExpiredOtpError(ResetError):
    pass


class TooManyAttemptsError(ResetError):
    pass


class InvalidResetTokenError(ResetError):
    pass


def _pepper() -> bytes:
    return get_settings().JWT_SECRET_KEY.encode("utf-8")


def hash_otp(otp: str) -> str:
    """HMAC-SHA256 hex of the OTP (peppered; DB-safe, non-reversible)."""
    return hmac.new(_pepper(), otp.encode("utf-8"), hashlib.sha256).hexdigest()


def generate_otp() -> str:
    """Cryptographically secure 6-digit OTP (CSPRNG, zero-padded)."""
    return f"{secrets.randbelow(1_000_000):06d}"


def _active_rows(db: Session, user_id: int):
    return (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.used_at.is_(None),
        )
        .order_by(PasswordResetToken.reset_id.desc())
    )


def _send_otp_email(to_email: str, otp: str) -> None:
    """Deliver the OTP via the existing email provider factory."""
    from app.notifications.preferences import Channel
    from app.notifications.providers import get_provider

    provider = get_provider(Channel.EMAIL)
    body = (
        "SmartQueue Password Reset\n\n"
        "Your verification code is:\n\n"
        f"{otp}\n\n"
        "This code expires in 10 minutes.\n\n"
        "If you did not request a password reset, you can ignore this email."
    )
    result = provider.send(
        to=to_email,
        subject="SmartQueue Password Reset",
        body=body,
        metadata={"type": "password_reset_otp"},
    )
    if not result.success:
        logger.warning("Password-reset email failed (provider=%s)", result.provider)
        raise EmailDeliveryError("Could not send verification email. Please try again later.")


def request_reset(db: Session, email: str) -> None:
    """Issue an OTP row + email. Unknown emails are silent (no enumeration).

    Raises ResendCooldownError / EmailDeliveryError for known users.
    """
    normalized = (email or "").strip().lower()
    user = db.query(User).filter(func.lower(User.email) == normalized).first()
    if user is None:
        return
    now = datetime.utcnow()
    latest = _active_rows(db, user.user_id).first()
    if latest is not None and (now - latest.created_at).total_seconds() < RESEND_COOLDOWN_SECONDS:
        raise ResendCooldownError("Please wait before requesting another code.")
    # Supersede older active rows: they can never verify again.
    for row in _active_rows(db, user.user_id).all():
        row.used_at = now
    otp = generate_otp()
    row = PasswordResetToken(
        user_id=user.user_id,
        otp_hash=hash_otp(otp),
        expires_at=now + timedelta(minutes=OTP_EXPIRY_MINUTES),
        attempts=0,
    )
    db.add(row)
    try:
        _send_otp_email(user.email, otp)
    except EmailDeliveryError:
        db.rollback()
        raise
    db.commit()


def verify_otp(db: Session, email: str, otp: str) -> str:
    """Verify the OTP; return a short-lived reset JWT bound to the row."""
    normalized = (email or "").strip().lower()
    user = db.query(User).filter(func.lower(User.email) == normalized).first()
    now = datetime.utcnow()
    row = _active_rows(db, user.user_id).first() if user is not None else None
    if row is None:
        raise InvalidOtpError("Invalid or expired verification code.")
    if row.expires_at <= now:
        raise ExpiredOtpError("Invalid or expired verification code.")
    if row.attempts >= OTP_MAX_ATTEMPTS:
        raise TooManyAttemptsError("Too many attempts. Please request a new code.")
    if row.verified_at is not None:
        # Already verified (token lost): re-issue without consuming attempts.
        return create_access_token(
            {"sub": str(user.user_id), "purpose": RESET_PURPOSE, "rid": row.reset_id},
            expires_minutes=RESET_TOKEN_EXPIRY_MINUTES,
        )
    if not hmac.compare_digest(row.otp_hash, hash_otp(otp or "")):
        row.attempts += 1
        db.commit()
        if row.attempts >= OTP_MAX_ATTEMPTS:
            raise TooManyAttemptsError("Too many attempts. Please request a new code.")
        raise InvalidOtpError("Invalid or expired verification code.")
    row.verified_at = now
    db.commit()
    return create_access_token(
        {"sub": str(user.user_id), "purpose": RESET_PURPOSE, "rid": row.reset_id},
        expires_minutes=RESET_TOKEN_EXPIRY_MINUTES,
    )


def reset_password(db: Session, reset_token: str, new_password: str) -> User:
    """Consume the reset JWT + row; set the new password hash."""
    payload = decode_access_token(reset_token or "")
    if not payload or payload.get("purpose") != RESET_PURPOSE:
        raise InvalidResetTokenError("Invalid or expired reset token.")
    try:
        user_id = int(payload.get("sub"))
        row_id = int(payload.get("rid"))
    except (TypeError, ValueError):
        raise InvalidResetTokenError("Invalid or expired reset token.")
    row = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.reset_id == row_id)
        .first()
    )
    if (
        row is None
        or row.user_id != user_id
        or row.verified_at is None
        or row.used_at is not None
    ):
        raise InvalidResetTokenError("Invalid or expired reset token.")
    user = db.query(User).filter(User.user_id == user_id).first()
    if user is None:
        raise InvalidResetTokenError("Invalid or expired reset token.")
    now = datetime.utcnow()
    user.password_hash = hash_password(new_password)
    row.used_at = now
    for other in _active_rows(db, user_id).all():
        if other.reset_id != row.reset_id:
            other.used_at = now
    db.commit()
    db.refresh(user)
    return user
