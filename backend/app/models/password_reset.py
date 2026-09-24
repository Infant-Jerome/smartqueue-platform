"""Password-reset token model (Forgot Password + Email OTP flow).

Table decision: a DB table IS justified -- OTP state (hash, expiry,
attempts, verified/used markers) must survive process restarts and be
enforced across workers; only DB predicates do that.

Security contract (enforced by ``app.services.password_reset_service``):
- ``otp_hash`` is HMAC-SHA256 (peppered with the JWT secret), never the
  raw 6-digit OTP. Raw OTPs exist only in the email body + request.
- The reset authorization is a stateless short-lived JWT
  (purpose=password_reset, bound to this row via ``rid``); no reset-token
  persistence beyond this row's ``verified_at``/``used_at`` markers.
- One row = one attempt stream: ``attempts`` caps verification tries;
  ``verified_at`` gates reset; ``used_at`` enforces one-time use.
- A new forgot-password request supersedes older active rows for the user.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String

from app.db.base import Base

# OTP / reset policy (single source of truth; service imports these).
OTP_LENGTH = 6
OTP_EXPIRY_MINUTES = 10
OTP_MAX_ATTEMPTS = 5
RESET_TOKEN_EXPIRY_MINUTES = 15
RESEND_COOLDOWN_SECONDS = 60


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    reset_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    otp_hash = Column(String(128), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    verified_at = Column(DateTime, nullable=True)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_password_reset_user_id", "user_id"),
        Index("ix_password_reset_user_active", "user_id", "used_at"),
    )

    def __repr__(self) -> str:
        return f"<PasswordResetToken reset_id={self.reset_id} user_id={self.user_id}>"
