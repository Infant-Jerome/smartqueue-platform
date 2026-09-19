"""Canonical Pydantic schemas (I2-Routes Phase 2: users/auth)."""

from datetime import date, datetime, time
from typing import Annotated, Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

try:  # EmailStr requires `email-validator`; use it when available.
    import email_validator  # noqa: F401

    from pydantic import EmailStr

    EmailType = EmailStr
    _HAS_EMAIL_VALIDATOR = True
except ImportError:  # Strict regex fallback (no new dependency).
    from pydantic import StringConstraints

    EmailType = Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=5,
            max_length=255,
            pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        ),
    ]
    _HAS_EMAIL_VALIDATOR = False

from app.models.user import UserRole


def _normalize_email(v: Any) -> Any:
    if isinstance(v, str):
        return v.strip().lower()
    return v


class UserCreate(BaseModel):
    """Registration input. Never accepts password_hash/role (extra=forbid)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=2, max_length=100)
    email: EmailType = Field(...)
    password: str = Field(..., min_length=6)
    phone: Optional[str] = Field(None, max_length=20)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v: Any) -> Any:
        return _normalize_email(v)


class UserLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailType = Field(...)
    password: str = Field(..., min_length=1)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v: Any) -> Any:
        return _normalize_email(v)


class UserResponse(BaseModel):
    """Public user view. Never exposes password_hash."""

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    user_id: int
    name: str
    email: str
    phone: Optional[str] = None
    role: UserRole
    created_at: datetime


class UserUpdate(BaseModel):
    """Self-editable fields only (no role/user_id)."""

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=2, max_length=100)
    phone: Optional[str] = Field(None, max_length=20)


class RoleUpdate(BaseModel):
    """Admin-only role assignment."""

    model_config = ConfigDict(extra="forbid")

    role: UserRole


class TokenResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class ServiceCreate(BaseModel):
    service_name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    duration_minutes: int = Field(..., gt=0, description="Duration in minutes")
    price: float = Field(..., gt=0)
    status: Optional[str] = "active"
    salon_id: Optional[int] = None


class ServiceUpdate(BaseModel):
    service_name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    duration_minutes: Optional[int] = Field(None, gt=0)
    price: Optional[float] = Field(None, gt=0)
    status: Optional[str] = None
    salon_id: Optional[int] = None


class ServiceResponse(BaseModel):
    service_id: int
    service_name: str
    description: Optional[str] = None
    duration_minutes: int
    price: float
    status: str
    salon_id: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class BarberCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    specialization: Optional[str] = None
    phone: Optional[str] = None
    availability_status: Optional[str] = "available"
    salon_id: Optional[int] = None
    user_id: Optional[int] = None
    experience_years: Optional[int] = Field(None, ge=0)


class BarberUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    specialization: Optional[str] = None
    phone: Optional[str] = None
    availability_status: Optional[str] = None
    salon_id: Optional[int] = None
    user_id: Optional[int] = None
    experience_years: Optional[int] = Field(None, ge=0)


class BarberResponse(BaseModel):
    barber_id: int
    name: str
    specialization: Optional[str] = None
    phone: Optional[str] = None
    availability_status: str
    salon_id: Optional[int] = None
    user_id: Optional[int] = None
    experience_years: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AppointmentCreate(BaseModel):
    """Booking input. Server computes end_time from the service duration.

    end_time/appointment_time are accepted for backward compatibility and
    validated against the server calculation (mismatch -> 422). Never trust
    client duration as source of truth; customer_id/user_id are forbidden.
    """

    model_config = ConfigDict(extra="forbid")

    barber_id: int
    service_id: int
    appointment_date: date = Field(..., description="Format: YYYY-MM-DD")
    start_time: time = Field(..., description="Format: HH:MM")
    end_time: Optional[time] = Field(None, description="Must match start_time + service duration if provided")
    appointment_time: Optional[time] = Field(None, description="Legacy alias for start_time; must match if provided")
    salon_id: Optional[int] = None
    booking_type: Optional[str] = "online"

    @model_validator(mode="after")
    def _check_alias(self):
        if self.appointment_time is not None and self.appointment_time != self.start_time:
            raise ValueError("appointment_time must match start_time")
        return self


class AppointmentUpdate(BaseModel):
    """Reschedule (appointment_date/start_time) and/or cancel (status) only."""

    model_config = ConfigDict(extra="forbid")

    appointment_date: Optional[date] = Field(None, description="Format: YYYY-MM-DD")
    start_time: Optional[time] = Field(None, description="Format: HH:MM")
    status: Optional[str] = None

    @model_validator(mode="after")
    def _require_at_least_one(self):
        if (
            self.appointment_date is None
            and self.start_time is None
            and self.status is None
        ):
            raise ValueError(
                "Provide at least one of appointment_date, start_time, status"
            )
        return self


class AppointmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    appointment_id: int
    customer_id: int
    salon_id: Optional[int] = None
    barber_id: int
    service_id: int
    appointment_date: date
    start_time: time
    end_time: time
    status: str
    booking_type: str = "online"
    created_at: datetime
    # Backward-compat extras (optional so Phase 3 contract stays strict).
    updated_at: Optional[datetime] = None
    queue_position: Optional[int] = None
    barber: Optional[BarberResponse] = None
    service: Optional[ServiceResponse] = None


class QueueCreate(BaseModel):
    """Internal-only create shape. Never accepts client position/estimate/status.

    Queue rows are derived server-side on booking; no customer route accepts
    queue_position, estimated_wait_minutes, status, or barber overrides.
    """

    model_config = ConfigDict(extra="forbid")

    appointment_id: int
    barber_id: Optional[int] = None
    salon_id: Optional[int] = None


class QueueResponse(BaseModel):
    queue_id: int
    appointment_id: int
    salon_id: Optional[int] = None
    barber_id: int
    queue_position: int
    joined_at: datetime
    estimated_wait_minutes: Optional[int] = None
    status: str
    updated_at: datetime
    appointment: Optional[AppointmentResponse] = None
    # SAWTE (Phase 5C, S2-Integrate): transient per-request confidence for the
    # wait estimate. Never persisted (no Queue column); computed on read via
    # ``queue_service`` and forwarded verbatim. Optional for back-compat.
    confidence: Optional[Any] = None

    class Config:
        from_attributes = True


class QueueUpdate(BaseModel):
    """Restricted admin/staff op. Prefer action endpoints (serve/complete/skip).

    Only whitelisted queue statuses are accepted (anything else -> 422).
    """

    model_config = ConfigDict(extra="forbid")

    status: Optional[str] = None

    @model_validator(mode="after")
    def _validate_status(self):
        allowed = {
            "waiting",
            "serving",
            "in_progress",
            "completed",
            "cancelled",
            "no_show",
        }
        if self.status is None:
            raise ValueError("status is required")
        if str(self.status).strip().lower() not in allowed:
            raise ValueError(
                "Invalid status. Allowed: "
                + ", ".join(sorted(allowed))
            )
        return self


class ServeNextRequest(BaseModel):
    """serve-next body. barber_id required (missing -> 422); salon_id optional."""

    model_config = ConfigDict(extra="forbid")

    barber_id: int
    salon_id: Optional[int] = None


class MyPositionResponse(BaseModel):
    """Customer-facing position view (subset of the service payload)."""

    model_config = ConfigDict(from_attributes=True)

    has_queue: bool = False
    queue_position: Optional[int] = None
    current_position: Optional[int] = None
    people_ahead: Optional[int] = None
    estimated_wait_minutes: Optional[int] = None
    status: Optional[str] = None
    currently_serving: Optional[int] = None
    appointment_status: Optional[str] = None
    message: Optional[str] = None
    # SAWTE (Phase 5C, S2-Integrate): confidence for estimated_wait_minutes,
    # forwarded verbatim from queue_service. Optional for back-compat.
    confidence: Optional[Any] = None


class MessageResponse(BaseModel):
    success: bool
    message: str
    data: Optional[dict | list | None] = None


class ApiResponse(BaseModel):
    success: bool = True
    message: str = "OK"
    data: Optional[Any] = None
