"""B1-Availability service (Phase 3).

Business rules:
- Barber must exist (else 404 ``Barber not found``).
- ``start_time < end_time`` (else 422). Midnight-crossing windows
  (``end <= start``) are rejected — windows must fit in one calendar day.
- ``status`` whitelist: available / unavailable / off (else 422).
- Overlapping windows for the same barber + date are rejected (409).
- Salon-hours helper: when the barber's salon sets both ``opening_time``
  and ``closing_time``, the availability window must lie inside
  ``[opening_time, closing_time]`` (else 422). Either bound NULL means no
  constraint. A salon config with ``closing_time <= opening_time``
  (midnight-crossing salon hours) is unsupported and rejected with 422.
- RBAC (roles normalized case-insensitively; ``staff`` == ``receptionist``):
  write (create/update) = admin + staff/receptionist (any barber) +
  barber owning the row via ``Barber.user_id`` link. Customers (and any
  other role) get 403. Barber A touching Barber B's rows gets 403.
  delete = admin hard-deletes; owner-barber hard-deletes own rows;
  staff/receptionist deactivates (sets ``status='unavailable'``) instead
  of deleting; everyone else gets 403.
"""

from datetime import date, time
from enum import Enum
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import Barber, BarberAvailability, Salon
from app.schemas.availability import ALLOWED_STATUSES

_STAFF_ROLES = frozenset({"staff", "receptionist"})
_DEACTIVATE_STATUS = "unavailable"


def _role_of(user) -> str:
    role = getattr(user, "role", "")
    if isinstance(role, Enum):
        role = role.value
    return str(role or "").strip().lower()


def _is_owner(barber: Barber, user) -> bool:
    return (
        barber is not None
        and getattr(barber, "user_id", None) is not None
        and barber.user_id == getattr(user, "user_id", None)
    )


def _get_barber_or_404(db: Session, barber_id: int) -> Barber:
    barber = db.query(Barber).filter(Barber.barber_id == barber_id).first()
    if barber is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Barber not found",
        )
    return barber


def _validate_time_range(start_time: time, end_time: time) -> None:
    # Midnight-crossing windows (end <= start) are rejected.
    if not start_time < end_time:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="end_time must be after start_time "
            "(midnight-crossing windows are rejected)",
        )


def _validate_status(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in ALLOWED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="status must be one of: available, unavailable, off",
        )
    return normalized


def validate_within_salon_hours(
    db: Session, barber: Barber, start_time: time, end_time: time
) -> None:
    """Salon-hours helper: window must fit inside salon opening/closing.

    - Barber without a salon (``salon_id`` NULL / salon row missing) → no
      constraint.
    - Either ``opening_time`` or ``closing_time`` NULL → no constraint.
    - Salon ``closing_time <= opening_time`` (midnight-crossing salon
      hours) is unsupported → 422.
    - Otherwise ``start_time >= opening_time`` and
      ``end_time <= closing_time`` are required → else 422.
    """
    salon = None
    if getattr(barber, "salon_id", None) is not None:
        salon = db.query(Salon).filter(Salon.salon_id == barber.salon_id).first()
    if salon is None:
        return
    opening = salon.opening_time
    closing = salon.closing_time
    if opening is None or closing is None:
        return
    if not opening < closing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Salon hours cross midnight (unsupported)",
        )
    if not (opening <= start_time and end_time <= closing):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Availability window must be within salon hours",
        )


def _check_overlap(
    db: Session,
    barber_id: int,
    day: date,
    start_time: time,
    end_time: time,
    exclude_id: Optional[int] = None,
) -> None:
    query = db.query(BarberAvailability).filter(
        BarberAvailability.barber_id == barber_id,
        BarberAvailability.date == day,
    )
    if exclude_id is not None:
        query = query.filter(BarberAvailability.availability_id != exclude_id)
    for existing in query.all():
        if start_time < existing.end_time and end_time > existing.start_time:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Availability window overlaps an existing entry",
            )


def enforce_write_access(barber: Barber, user) -> None:
    """Create/update guard: admin + staff(any barber) + owner-barber.

    Raises 403 for customers (and any other role) and for a barber acting
    on another barber's row (Barber A vs Barber B).
    """
    role = _role_of(user)
    if role == "admin" or role in _STAFF_ROLES:
        return
    if role == "barber" and _is_owner(barber, user):
        return
    if role == "barber":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Barbers can only manage their own availability",
        )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Insufficient permissions",
    )


def get_availability_or_404(db: Session, availability_id: int) -> BarberAvailability:
    entry = (
        db.query(BarberAvailability)
        .filter(BarberAvailability.availability_id == availability_id)
        .first()
    )
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Availability not found",
        )
    return entry


def create_availability(db: Session, user, data) -> BarberAvailability:
    barber = _get_barber_or_404(db, data.barber_id)
    enforce_write_access(barber, user)
    _validate_time_range(data.start_time, data.end_time)
    status_value = _validate_status(data.status)
    validate_within_salon_hours(db, barber, data.start_time, data.end_time)
    _check_overlap(db, data.barber_id, data.date, data.start_time, data.end_time)
    entry = BarberAvailability(
        barber_id=data.barber_id,
        date=data.date,
        start_time=data.start_time,
        end_time=data.end_time,
        status=status_value,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def list_availabilities(
    db: Session,
    barber_id: Optional[int] = None,
    day: Optional[date] = None,
):
    query = db.query(BarberAvailability).order_by(
        BarberAvailability.date.asc(),
        BarberAvailability.start_time.asc(),
    )
    if barber_id is not None:
        query = query.filter(BarberAvailability.barber_id == barber_id)
    if day is not None:
        query = query.filter(BarberAvailability.date == day)
    return query.all()


def update_availability(db: Session, user, availability_id: int, data) -> BarberAvailability:
    entry = get_availability_or_404(db, availability_id)
    current_barber = _get_barber_or_404(db, entry.barber_id)
    enforce_write_access(current_barber, user)

    patch = data.model_dump(exclude_unset=True)

    new_barber_id = patch.get("barber_id", entry.barber_id)
    target_barber = current_barber
    if new_barber_id != entry.barber_id:
        target_barber = _get_barber_or_404(db, new_barber_id)
        # A barber must also own the destination row (A -> B move forbidden).
        enforce_write_access(target_barber, user)

    new_date = patch.get("date", entry.date)
    new_start = patch.get("start_time", entry.start_time)
    new_end = patch.get("end_time", entry.end_time)
    if "start_time" in patch or "end_time" in patch:
        _validate_time_range(new_start, new_end)

    if "status" in patch and patch["status"] is not None:
        patch["status"] = _validate_status(patch["status"])

    if (
        new_barber_id != entry.barber_id
        or new_date != entry.date
        or new_start != entry.start_time
        or new_end != entry.end_time
    ):
        validate_within_salon_hours(db, target_barber, new_start, new_end)
        _check_overlap(
            db,
            new_barber_id,
            new_date,
            new_start,
            new_end,
            exclude_id=entry.availability_id,
        )

    for field, value in patch.items():
        if value is not None:
            setattr(entry, field, value)

    db.commit()
    db.refresh(entry)
    return entry


def delete_availability(db: Session, user, availability_id: int):
    """Delete or deactivate.

    Returns ``(entry, hard_deleted: bool)``. Admin and the owner-barber
    hard-delete; staff/receptionist deactivates (``status='unavailable'``);
    everyone else (customers, non-owner barbers) gets 403.
    """
    entry = get_availability_or_404(db, availability_id)
    barber = _get_barber_or_404(db, entry.barber_id)
    role = _role_of(user)
    if role == "admin" or (role == "barber" and _is_owner(barber, user)):
        db.delete(entry)
        db.commit()
        return None, True
    if role in _STAFF_ROLES:
        entry.status = _DEACTIVATE_STATUS
        db.commit()
        db.refresh(entry)
        return entry, False
    if role == "barber":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Barbers can only manage their own availability",
        )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Insufficient permissions",
    )
