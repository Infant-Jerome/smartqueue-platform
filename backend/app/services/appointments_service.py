"""Booking engine (B2-BookingService, SmartQueue Phase 3).

Canonical appointment lifecycle owned here. No AI, no notifications,
no queue serve-next/reorder/estimates engine (Phase 4 owns the queue engine).

Status constants: booked, confirmed, waiting, in_progress, completed,
cancelled, no_show.
Booking-type whitelist: online, walk_in (default online).

Concurrency note (SQLite vs Postgres/MySQL):
  Overlap prevention is an application-level interval check
  (existing.start < req.end AND existing.end > req.start) because time
  ranges cannot be expressed as a plain UNIQUE constraint. The create path
  runs inside a single DB transaction with a deterministic row ordering
  (ORDER BY appointment_id) and rolls back on any failure. On SQLite this
  serializes writers via the database lock; on Postgres/MySQL callers
  should run this at READ COMMITTED or higher and, for hard race-proofing,
  add a SELECT ... FOR UPDATE on the barber-day rows or a predicate/exclusion
  constraint. This module does NOT claim race-proofing beyond
  transaction + deterministic ordering + rollback.
"""

from datetime import date, datetime, time, timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import (
    Appointment,
    AppointmentStatusHistory,
    Barber,
    BarberAvailability,
    Queue,
    Salon,
    Service,
    User,
)
from app.schemas.schemas import AppointmentCreate, AppointmentUpdate

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

APPOINTMENT_STATUSES = (
    "booked",
    "confirmed",
    "waiting",
    "in_progress",
    "completed",
    "cancelled",
    "no_show",
)

BOOKING_TYPES = ("online", "walk_in")
DEFAULT_BOOKING_TYPE = "online"

TERMINAL_STATUSES = ("completed", "cancelled", "no_show")

# Terminal (non-blocking) statuses ignored by overlap checks.
_IGNORED_OVERLAP_STATUSES = ("cancelled", "no_show")

# Allowed status transitions. Illegal transitions => 400.
STATUS_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "booked": ("confirmed", "cancelled", "no_show"),
    "confirmed": ("waiting", "cancelled"),
    "waiting": ("in_progress", "cancelled", "no_show"),
    "in_progress": ("completed",),
    "completed": (),
    "cancelled": (),
    "no_show": (),
}

# Minimal appointment -> queue status mirror. Phase 4 owns the queue engine;
# this map only keeps the derived queue row consistent on booking updates.
_APPT_TO_QUEUE_STATUS = {
    "booked": "waiting",
    "confirmed": "waiting",
    "waiting": "waiting",
    "in_progress": "serving",
    "completed": "completed",
    "cancelled": "cancelled",
    "no_show": "no_show",
}


# ---------------------------------------------------------------------------
# Coercion / interval helpers
# ---------------------------------------------------------------------------

def _coerce_date(value) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid date format. Use YYYY-MM-DD",
        )


def _coerce_time(value, label: str = "time") -> time:
    if isinstance(value, time):
        # Drop tzinfo/microseconds for consistent comparisons.
        return value.replace(tzinfo=None)
    try:
        return time.fromisoformat(value)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {label} format. Use HH:MM",
        )


def _overlaps(start_a: time, end_a: time, start_b: time, end_b: time) -> bool:
    return start_a < end_b and end_a > start_b


def _calc_end_time(start: time, duration_minutes: int) -> time:
    return (datetime.combine(date.today(), start) + timedelta(minutes=duration_minutes)).time()


# ---------------------------------------------------------------------------
# Entity loaders
# ---------------------------------------------------------------------------

def _load_salon(db: Session, salon_id: int | None) -> Salon | None:
    """Load an explicitly requested salon (404 if missing, 400 if inactive).

    Returns None when no salon_id is given; callers may fall back to the
    barber/service salon for hours checks.
    """
    if salon_id is None:
        return None
    salon = db.query(Salon).filter(Salon.salon_id == salon_id).first()
    if not salon:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Salon not found",
        )
    if salon.status == "inactive":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Salon is not active",
        )
    return salon


def _load_service(db: Session, service_id: int) -> Service:
    service = db.query(Service).filter(Service.service_id == service_id).first()
    if not service:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Service not found",
        )
    if service.status == "inactive":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Service is not available",
        )
    return service


def _load_barber(db: Session, barber_id: int) -> Barber:
    barber = db.query(Barber).filter(Barber.barber_id == barber_id).first()
    if not barber:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Barber not found",
        )
    if barber.availability_status in ("inactive", "unavailable"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Barber is not available",
        )
    return barber


def _resolve_salon(
    db: Session,
    requested_id: int | None,
    barber: Barber,
    service: Service,
) -> Salon | None:
    """Resolve the effective salon for hours / belonging checks.

    Explicit salon_id => 404/400 enforced. Otherwise fall back to the
    barber's (then service's) salon; None means "no salon context" and
    salon-scoped checks are skipped (legacy rows carry NULL salon_id).
    """
    if requested_id is not None:
        return _load_salon(db, requested_id)
    fallback_id = barber.salon_id or service.salon_id
    if fallback_id is None:
        return None
    salon = db.query(Salon).filter(Salon.salon_id == fallback_id).first()
    if salon is not None and salon.status == "inactive":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Salon is not active",
        )
    return salon


def _enforce_belongs_to_salon(barber: Barber, service: Service, salon: Salon | None) -> None:
    """Service/barber must belong to the salon (400). Only enforced when
    both sides carry a non-null salon_id (legacy NULL rows are tolerated)."""
    if salon is None:
        return
    if service.salon_id is not None and service.salon_id != salon.salon_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Service does not belong to this salon",
        )
    if barber.salon_id is not None and barber.salon_id != salon.salon_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Barber does not belong to this salon",
        )


def _enforce_salon_hours(salon: Salon | None, start: time, end: time) -> None:
    """Booking must fit within salon hours (400). Skipped when the salon
    is unknown or has no opening/closing times configured."""
    if salon is None or salon.opening_time is None or salon.closing_time is None:
        return
    opening = _coerce_time(salon.opening_time, "opening_time")
    closing = _coerce_time(salon.closing_time, "closing_time")
    if not (opening <= start and end <= closing):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Booking is outside salon working hours",
        )


def _enforce_barber_availability(
    db: Session, barber_id: int, appt_date: date, start: time, end: time
) -> None:
    """Require a covering BarberAvailability window for the date (400).

    Only enforced when availability rows exist for that barber+date; a
    barber with no configured windows for the date is treated as openly
    scheduled (keeps legacy bookings working).
    """
    windows = (
        db.query(BarberAvailability)
        .filter(
            BarberAvailability.barber_id == barber_id,
            BarberAvailability.date == appt_date,
        )
        .all()
    )
    if not windows:
        return
    for window in windows:
        if window.status != "available":
            continue
        window_start = _coerce_time(window.start_time, "start_time")
        window_end = _coerce_time(window.end_time, "end_time")
        if window_start <= start and end <= window_end:
            return
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Barber is not available at the requested time",
    )


def _validate_booking_type(booking_type: str | None) -> str:
    value = booking_type or DEFAULT_BOOKING_TYPE
    if value not in BOOKING_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid booking_type. Allowed: {', '.join(BOOKING_TYPES)}",
        )
    return value


def _validate_transition(current: str, target: str) -> None:
    if target not in APPOINTMENT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status '{target}'",
        )
    if target == current:
        return
    allowed = STATUS_TRANSITIONS.get(current, ())
    if target not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot transition appointment from '{current}' to '{target}'",
        )


def _sync_queue_status(db: Session, appointment: Appointment, new_status: str) -> None:
    """Mirror the appointment status onto the derived queue row (minimal;
    queue numbering/serve-next/reorder/estimates belong to Phase 4)."""
    queue_entry = (
        db.query(Queue).filter(Queue.appointment_id == appointment.appointment_id).first()
    )
    if queue_entry is not None:
        queue_entry.status = _APPT_TO_QUEUE_STATUS.get(new_status, new_status)


# ---------------------------------------------------------------------------
# Read API (unchanged behavior)
# ---------------------------------------------------------------------------

def list_appointments(db: Session, user: User):
    if user.role in ("admin", "staff"):
        return (
            db.query(Appointment)
            .order_by(Appointment.created_at.desc())
            .all()
        )
    return (
        db.query(Appointment)
        .filter(Appointment.customer_id == user.user_id)
        .order_by(Appointment.created_at.desc())
        .all()
    )


def get_appointment(db: Session, appointment_id: int, user: User) -> Appointment:
    appointment = (
        db.query(Appointment)
        .filter(Appointment.appointment_id == appointment_id)
        .first()
    )
    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found",
        )

    if user.role == "customer" and appointment.customer_id != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    return appointment


# ---------------------------------------------------------------------------
# Booking engine
# ---------------------------------------------------------------------------

def create_appointment(db: Session, user: User, data: AppointmentCreate) -> Appointment:
    # 1. Load entities: salon (404 / inactive 400), service (404 / inactive
    #    400, must belong to salon 400), barber (404 / inactive or
    #    unavailable 400, must belong to salon 400).
    barber = _load_barber(db, data.barber_id)
    service = _load_service(db, data.service_id)
    salon = _resolve_salon(db, data.salon_id, barber, service)
    _enforce_belongs_to_salon(barber, service, salon)

    # 2. Date guards: no past dates; same-day bookings must start in the future.
    appt_date = _coerce_date(data.appointment_date)
    today = date.today()
    if appt_date < today:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot book appointments in the past",
        )

    start = _coerce_time(data.start_time, "start_time")
    if appt_date == today and start <= datetime.now().time().replace(tzinfo=None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot book an appointment in the past",
        )

    # 3. Server-calculated end_time wins. A client-supplied end_time that
    #    disagrees with start + service.duration_minutes => 422.
    end = _calc_end_time(start, service.duration_minutes)
    if data.end_time is not None:
        client_end = _coerce_time(data.end_time, "end_time")
        if client_end != end:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="end_time does not match start_time + service duration",
            )
    if not start < end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end_time must be after start_time",
        )

    # 4. Salon hours + barber availability windows.
    _enforce_salon_hours(salon, start, end)
    _enforce_barber_availability(db, barber.barber_id, appt_date, start, end)

    booking_type = _validate_booking_type(data.booking_type)

    # 5. Overlap checks (deterministic order; ignored: cancelled/no_show).
    #    Same barber + date => 409; same customer (any barber, same date)
    #    keeps existing behavior => 409.
    day_bookings = (
        db.query(Appointment)
        .filter(
            Appointment.barber_id == data.barber_id,
            Appointment.appointment_date == appt_date,
            Appointment.status.notin_(_IGNORED_OVERLAP_STATUSES),
        )
        .order_by(Appointment.appointment_id.asc())
        .all()
    )
    for existing in day_bookings:
        if _overlaps(start, end, existing.start_time, existing.end_time):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Sorry, this time slot was just booked by another customer. Please select another time.",
            )

    my_day_bookings = (
        db.query(Appointment)
        .filter(
            Appointment.customer_id == user.user_id,
            Appointment.appointment_date == appt_date,
            Appointment.status.notin_(_IGNORED_OVERLAP_STATUSES),
        )
        .order_by(Appointment.appointment_id.asc())
        .all()
    )
    for conflicting in my_day_bookings:
        if _overlaps(start, end, conflicting.start_time, conflicting.end_time):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You already have an appointment at this time",
            )

    # Queue numbering is 1-based per day (queue_position 1, 2, 3, ...).
    # Minimal per-day logic only; Phase 4 owns the queue engine.
    last_queue = (
        db.query(Queue)
        .join(Appointment, Queue.appointment_id == Appointment.appointment_id)
        .filter(Appointment.appointment_date == appt_date)
        .order_by(Queue.queue_position.desc())
        .first()
    )
    next_position = (last_queue.queue_position + 1) if last_queue else 1

    # 6. Transactional create: Appointment(status=booked) + minimal Queue row
    #    + initial AppointmentStatusHistory(old=None, new=booked). Status is
    #    always booked here; clients cannot set completed (or anything else)
    #    on create.
    try:
        appointment = Appointment(
            customer_id=user.user_id,
            salon_id=salon.salon_id if salon is not None else data.salon_id,
            barber_id=data.barber_id,
            service_id=data.service_id,
            appointment_date=appt_date,
            start_time=start,
            end_time=end,
            status="booked",
            booking_type=booking_type,
        )
        db.add(appointment)
        db.flush()

        queue_entry = Queue(
            appointment_id=appointment.appointment_id,
            salon_id=appointment.salon_id,
            barber_id=data.barber_id,
            queue_position=next_position,
            estimated_wait_minutes=service.duration_minutes,
            status="waiting",
        )
        db.add(queue_entry)

        history = AppointmentStatusHistory(
            appointment_id=appointment.appointment_id,
            old_status=None,
            new_status="booked",
        )
        db.add(history)

        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    db.refresh(appointment)

    try:  # WS2: booking-creation emit post-commit only (never break REST)
        from app.services import queue_events as _qe

        _qe.publish_creation(queue_entry, appointment)
    except Exception:
        pass

    return appointment


# ---------------------------------------------------------------------------
# Status transitions (update / cancel)
# ---------------------------------------------------------------------------

def _apply_status_transition(
    db: Session, appointment: Appointment, target: str
) -> Appointment:
    _validate_transition(appointment.status, target)
    if target == appointment.status:
        return appointment
    old_status = appointment.status
    try:
        appointment.status = target
        _sync_queue_status(db, appointment, target)
        db.add(
            AppointmentStatusHistory(
                appointment_id=appointment.appointment_id,
                old_status=old_status,
                new_status=target,
            )
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    db.refresh(appointment)
    try:  # WS2: cancel/update emit post-commit only (never break REST)
        from app.services import queue_events as _qe

        if target == "cancelled":
            _qe.publish_cancel(None, appointment)
        else:
            _qe.publish_updated(None, appointment)
    except Exception:
        pass
    return appointment


def update_appointment(
    db: Session, appointment_id: int, data: AppointmentUpdate, user: User
) -> Appointment:
    appointment = (
        db.query(Appointment)
        .filter(Appointment.appointment_id == appointment_id)
        .first()
    )
    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found",
        )

    if user.role == "customer":
        if appointment.customer_id != user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )
        if data.status not in ("cancelled", None):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Customers can only cancel appointments",
            )

    if data.status:
        return _apply_status_transition(db, appointment, data.status)

    return appointment


def cancel_appointment(db: Session, appointment_id: int, user: User) -> Appointment:
    """Cancel an appointment via the transition map (booked/confirmed/
    waiting -> cancelled; illegal => 400). Customers may only cancel their
    own rows (403 otherwise)."""
    appointment = (
        db.query(Appointment)
        .filter(Appointment.appointment_id == appointment_id)
        .first()
    )
    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found",
        )
    if user.role == "customer" and appointment.customer_id != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    return _apply_status_transition(db, appointment, "cancelled")


def delete_appointment(db: Session, appointment_id: int) -> None:
    appointment = (
        db.query(Appointment)
        .filter(Appointment.appointment_id == appointment_id)
        .first()
    )
    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found",
        )

    db.delete(appointment)
    db.commit()
