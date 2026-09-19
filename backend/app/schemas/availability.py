"""B1-Availability schemas (Phase 3).

Canonical model: ``BarberAvailability(barber_id, date, start_time, end_time,
status)`` (see ``app.models.availability``).

Rules enforced here (Pydantic level, surfaced as HTTP 422 via the
``RequestValidationError`` handler in ``app.main``):
- ``start_time < end_time`` is required. Midnight-crossing windows (where
  ``end_time <= start_time``, e.g. 22:00-02:00) are REJECTED — availability
  windows must lie within a single calendar day.
- ``status`` whitelist: ``available`` / ``unavailable`` / ``off``
  (case-insensitive input, normalized to lowercase).
"""

from datetime import date, datetime, time
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ALLOWED_STATUSES = frozenset({"available", "unavailable", "off"})


def _normalize_status(v):
    if isinstance(v, str):
        return v.strip().lower()
    return v


class AvailabilityCreate(BaseModel):
    """Create payload for a barber daily working window."""

    model_config = ConfigDict(extra="forbid")

    barber_id: int = Field(..., gt=0)
    date: date
    start_time: time
    end_time: time
    status: str = Field(default="available")

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, v):
        v = _normalize_status(v)
        if v not in ALLOWED_STATUSES:
            raise ValueError(
                "status must be one of: available, unavailable, off"
            )
        return v

    @model_validator(mode="after")
    def validate_time_range(self):
        if self.start_time is not None and self.end_time is not None:
            if not self.start_time < self.end_time:
                raise ValueError(
                    "end_time must be after start_time "
                    "(midnight-crossing windows are rejected)"
                )
        return self


class AvailabilityUpdate(BaseModel):
    """Partial update payload; every field optional."""

    model_config = ConfigDict(extra="forbid")

    barber_id: Optional[int] = Field(default=None, gt=0)
    date: Optional[date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    status: Optional[str] = None

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, v):
        if v is None:
            return v
        v = _normalize_status(v)
        if v not in ALLOWED_STATUSES:
            raise ValueError(
                "status must be one of: available, unavailable, off"
            )
        return v

    @model_validator(mode="after")
    def validate_time_range(self):
        if self.start_time is not None and self.end_time is not None:
            if not self.start_time < self.end_time:
                raise ValueError(
                    "end_time must be after start_time "
                    "(midnight-crossing windows are rejected)"
                )
        return self


class AvailabilityResponse(BaseModel):
    """Public availability view."""

    model_config = ConfigDict(from_attributes=True)

    availability_id: int
    barber_id: int
    date: date
    start_time: time
    end_time: time
    status: str
    created_at: datetime
    updated_at: datetime
