"""Appointment routes (B3-Routes, Phase 3).

Thin HTTP layer over the booking service (``app.services``). This module
owns request/response shape, authz scoping and status codes; slot math and
persistence rules live in the service layer. Server always derives
``end_time`` from the service duration -- client duration is never trusted.
"""

from datetime import date as _date
from datetime import datetime, time as _time
from datetime import timedelta
from types import SimpleNamespace
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.response import ok
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
from app.schemas.schemas import (
    AppointmentCreate,
    AppointmentResponse,
    AppointmentUpdate,
    ApiResponse,
)
from app.services import appointments_service

router = APIRouter()

_STAFF_ROLES = frozenset({"staff", "receptionist"})
_TERMINAL_RESCHEDULE_BLOCK = frozenset({"completed", "cancelled"})
_INACTIVE_APPOINTMENT = frozenset({"cancelled", "no_show"})


def _role_of(user: User) -> str:
    role = getattr(user, "role", "")
    value = getattr(role, "value", role)
    return str(value or "").strip().lower()


def _to_response(appointment) -> AppointmentResponse:
    """Serialize an appointment, preserving queue_position compat."""
    if isinstance(appointment, dict):
        data = dict(appointment)
        qp = data.pop("queue_position", None)
        response = AppointmentResponse.model_validate(data)
        if isinstance(qp, int):
            response.queue_position = qp
        return response
    response = AppointmentResponse.model_validate(appointment)
    queue = getattr(appointment, "queue", None)
    if queue is not None and not isinstance(queue, dict):
        qp = getattr(queue, "queue_position", None)
        if isinstance(qp, int):
            response.queue_position = qp
    elif isinstance(queue, dict) and isinstance(queue.get("queue_position"), int):
        response.queue_position = queue["queue_position"]
    else:
        qp = getattr(appointment, "queue_position", None)
        if isinstance(qp, int):
            response.queue_position = qp
    return response


def _end_time(start: _time, duration_minutes: int) -> _time:
    base = datetime.combine(_date.today(), start) + timedelta(
        minutes=int(duration_minutes)
    )
    return base.time().replace(microsecond=0)


def _overlaps(a_start: _time, a_end: _time, b_start: _time, b_end: _time) -> bool:
    return a_start < b_end and a_end > b_start


def _get_or_404(db: Session, appointment_id: int) -> Appointment:
    appointment = (
        db.query(Appointment)
        .filter(Appointment.appointment_id == appointment_id)
        .first()
    )
    if appointment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found"
        )
    return appointment


def _barber_profile(db: Session, user: User) -> Optional[Barber]:
    return db.query(Barber).filter(Barber.user_id == user.user_id).first()


def _require_read_access(db: Session, appointment: Appointment, user: User) -> None:
    role = _role_of(user)
    if role == "admin" or role in _STAFF_ROLES:
        return
    if role == "barber":
        profile = _barber_profile(db, user)
        if profile is not None and appointment.barber_id == profile.barber_id:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
        )
    # Customers (and any other role) see only their own rows.
    if appointment.customer_id != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
        )


def _require_write_access(db: Session, appointment: Appointment, user: User) -> None:
    """PUT/DELETE authz: owner, assigned barber, or staff/admin."""
    role = _role_of(user)
    if role == "admin" or role in _STAFF_ROLES:
        return
    if role == "barber":
        profile = _barber_profile(db, user)
        if profile is not None and appointment.barber_id == profile.barber_id:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
        )
    if appointment.customer_id != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
        )


def _resolve_salon(
    db: Session, salon_id: Optional[int], barber: Barber, service: Service
) -> Optional[Salon]:
    sid = salon_id or getattr(barber, "salon_id", None) or getattr(
        service, "salon_id", None
    )
    if sid is None:
        return None
    return db.query(Salon).filter(Salon.salon_id == sid).first()


def _check_salon_hours(
    db: Session,
    salon_id: Optional[int],
    barber: Barber,
    service: Service,
    start: _time,
    end: _time,
) -> None:
    salon = _resolve_salon(db, salon_id, barber, service)
    if salon is None:
        return
    opening = getattr(salon, "opening_time", None)
    closing = getattr(salon, "closing_time", None)
    if opening is None or closing is None:
        return
    if not (opening <= start and end <= closing and start < end):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Appointment time is outside salon operating hours.",
        )


def _check_barber_availability(
    db: Session, barber: Barber, appt_date: _date, start: _time, end: _time
) -> None:
    if (barber.availability_status or "").strip().lower() == "inactive":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Barber is not available for the selected time.",
        )
    windows = (
        db.query(BarberAvailability)
        .filter(
            BarberAvailability.barber_id == barber.barber_id,
            BarberAvailability.date == appt_date,
        )
        .all()
    )
    if not windows:
        return
    for w in windows:
        w_status = str(getattr(w, "status", "available") or "available").lower()
        if w_status in ("unavailable", "off", "blocked", "inactive"):
            if _overlaps(start, end, w.start_time, w.end_time):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Barber is not available for the selected time.",
                )
    available = [w for w in windows if str(getattr(w, "status", "available") or "available").lower() == "available"]
    if available and not any(
        start >= w.start_time and end <= w.end_time for w in available
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Barber is not available for the selected time.",
        )


def _check_slot_conflicts(
    db: Session,
    barber_id: int,
    customer_id: int,
    appt_date: _date,
    start: _time,
    end: _time,
    exclude_id: Optional[int] = None,
) -> None:
    """Same overlap engine as booking: barber slot + same-customer checks."""
    q = db.query(Appointment).filter(
        Appointment.barber_id == barber_id,
        Appointment.appointment_date == appt_date,
        Appointment.status.notin_(_INACTIVE_APPOINTMENT),
    )
    if exclude_id is not None:
        q = q.filter(Appointment.appointment_id != exclude_id)
    for existing in q.all():
        if _overlaps(start, end, existing.start_time, existing.end_time):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Selected time conflicts with an existing appointment.",
            )
    mine = db.query(Appointment).filter(
        Appointment.customer_id == customer_id,
        Appointment.appointment_date == appt_date,
        Appointment.status.notin_(_INACTIVE_APPOINTMENT),
    )
    if exclude_id is not None:
        mine = mine.filter(Appointment.appointment_id != exclude_id)
    for conflicting in mine.all():
        if _overlaps(start, end, conflicting.start_time, conflicting.end_time):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You already have an appointment at this time",
            )


def _record_history(
    db: Session, appointment_id: int, old_status: Optional[str], new_status: str
) -> None:
    db.add(
        AppointmentStatusHistory(
            appointment_id=appointment_id,
            old_status=old_status,
            new_status=new_status,
        )
    )


def _sync_queue_status(db: Session, appointment_id: int, new_status: str) -> None:
    entry = (
        db.query(Queue).filter(Queue.appointment_id == appointment_id).first()
    )
    if entry is not None:
        entry.status = new_status


def _service_cancel(db: Session, appointment: Appointment, user: User):
    """Use the booking service cancel path when it exists (creates history)."""
    for name in ("cancel_appointment", "cancel"):
        fn = getattr(appointments_service, name, None)
        if callable(fn):
            try:
                result = fn(db, appointment.appointment_id, user)
            except TypeError:
                try:
                    result = fn(db, appointment.appointment_id)
                except HTTPException:
                    raise
                except Exception:
                    break
            return result
    return None


def _apply_cancel(db: Session, appointment: Appointment) -> Appointment:
    old_status = appointment.status
    appointment.status = "cancelled"
    _sync_queue_status(db, appointment.appointment_id, "cancelled")
    _record_history(db, appointment.appointment_id, old_status, "cancelled")
    db.commit()
    db.refresh(appointment)
    try:  # WS2: cancel emit post-commit only (this path bypasses the service)
        from app.services import queue_events as _qe

        entry = db.query(Queue).filter(Queue.appointment_id == appointment.appointment_id).first()
        _qe.publish_cancel(entry, appointment)
    except Exception:
        pass
    return appointment


@router.get("", response_model=ApiResponse)
def list_appointments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    role = _role_of(current_user)
    query = db.query(Appointment)
    if role == "admin" or role in _STAFF_ROLES:
        appointments = query.order_by(Appointment.created_at.desc()).all()
    elif role == "barber":
        profile = _barber_profile(db, current_user)
        if profile is None:
            return ok([])
        appointments = (
            query.filter(Appointment.barber_id == profile.barber_id)
            .order_by(Appointment.created_at.desc())
            .all()
        )
    else:
        appointments = (
            query.filter(Appointment.customer_id == current_user.user_id)
            .order_by(Appointment.created_at.desc())
            .all()
        )
    return ok([_to_response(a) for a in appointments])


@router.get("/{appointment_id}", response_model=ApiResponse)
def get_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    appointment = _get_or_404(db, appointment_id)
    _require_read_access(db, appointment, current_user)
    return ok(_to_response(appointment))


@router.post("", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
def create_appointment(
    data: AppointmentCreate,
    customer_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    role = _role_of(current_user)
    effective_user = current_user
    if customer_id is not None and customer_id != current_user.user_id:
        if role == "customer":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Customers cannot book on behalf of others",
            )
        if role not in ("admin", *_STAFF_ROLES):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
            )
        target = db.query(User).filter(User.user_id == customer_id).first()
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found"
            )
        effective_user = target

    barber = db.query(Barber).filter(Barber.barber_id == data.barber_id).first()
    if barber is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Barber not found"
        )
    service = db.query(Service).filter(Service.service_id == data.service_id).first()
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Service not found"
        )
    if (service.status or "").strip().lower() == "inactive":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Service is not available",
        )
    if data.appointment_date < _date.today():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot book appointments in the past",
        )

    start = data.start_time
    end = _end_time(start, service.duration_minutes)
    if data.end_time is not None and data.end_time != end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="end_time does not match start_time + service duration",
        )
    _check_salon_hours(db, data.salon_id, barber, service, start, end)
    _check_barber_availability(db, barber, data.appointment_date, start, end)

    # Server-derived slot payload: end_time computed from service duration,
    # never taken from the client.
    slot = SimpleNamespace(
        barber_id=data.barber_id,
        service_id=data.service_id,
        appointment_date=data.appointment_date,
        start_time=start,
        end_time=end,
        salon_id=data.salon_id,
        booking_type=data.booking_type or "online",
    )
    try:
        appointment = appointments_service.create_appointment(
            db, effective_user, slot  # type: ignore[arg-type]
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else ""
        if exc.status_code == status.HTTP_409_CONFLICT and "just booked" in detail:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Selected time conflicts with an existing appointment.",
            )
        raise
    return ok(_to_response(appointment), message="Appointment booked successfully")


@router.put("/{appointment_id}", response_model=ApiResponse)
def update_appointment(
    appointment_id: int,
    data: AppointmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    appointment = _get_or_404(db, appointment_id)
    _require_write_access(db, appointment, current_user)
    role = _role_of(current_user)

    wants_reschedule = (
        data.appointment_date is not None or data.start_time is not None
    )
    wants_status = data.status is not None

    if wants_reschedule and (appointment.status or "").lower() in _TERMINAL_RESCHEDULE_BLOCK:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot reschedule a completed or cancelled appointment.",
        )

    if wants_status and role == "customer":
        new_status = str(data.status or "").strip().lower()
        if new_status != "cancelled":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Customers can only cancel appointments",
            )

    if wants_reschedule:
        new_date = data.appointment_date or appointment.appointment_date
        new_start = data.start_time or appointment.start_time
        if new_date < _date.today():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot book appointments in the past",
            )
        service = (
            db.query(Service)
            .filter(Service.service_id == appointment.service_id)
            .first()
        )
        if service is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Service not found"
            )
        barber = (
            db.query(Barber)
            .filter(Barber.barber_id == appointment.barber_id)
            .first()
        )
        if barber is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Barber not found"
            )
        new_end = _end_time(new_start, service.duration_minutes)
        _check_salon_hours(
            db, appointment.salon_id, barber, service, new_start, new_end
        )
        _check_barber_availability(db, barber, new_date, new_start, new_end)
        _check_slot_conflicts(
            db,
            appointment.barber_id,
            appointment.customer_id,
            new_date,
            new_start,
            new_end,
            exclude_id=appointment.appointment_id,
        )
        appointment.appointment_date = new_date
        appointment.start_time = new_start
        appointment.end_time = new_end

    if wants_status:
        new_status = str(data.status)
        current = appointment.status
        if new_status != current:
            if (current or "").lower() == "completed":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot modify a completed appointment.",
                )
            if (current or "").lower() == "cancelled":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot modify a cancelled appointment.",
                )
            appointment.status = new_status
            _sync_queue_status(db, appointment.appointment_id, new_status)
            _record_history(db, appointment.appointment_id, current, new_status)

    db.commit()
    db.refresh(appointment)
    try:  # WS2: reschedule/status emit post-commit only (this path bypasses the service)
        from app.services import queue_events as _qe

        entry = db.query(Queue).filter(Queue.appointment_id == appointment.appointment_id).first()
        if wants_status and str(data.status or "").strip().lower() == "cancelled":
            _qe.publish_cancel(entry, appointment)
        else:
            _qe.publish_updated(entry, appointment)
    except Exception:
        pass
    return ok(_to_response(appointment), message="Appointment updated successfully")


@router.delete("/{appointment_id}", response_model=ApiResponse)
def cancel_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cancel semantics (no hard delete): eligible own/assigned cancellations
    flip status to ``cancelled`` via the service path and record history."""
    appointment = _get_or_404(db, appointment_id)
    _require_write_access(db, appointment, current_user)

    current = (appointment.status or "").lower()
    if current == "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot cancel a completed appointment.",
        )
    if current == "cancelled":
        return ok(_to_response(appointment), message="Appointment cancelled successfully")

    cancelled = _service_cancel(db, appointment, current_user)
    if isinstance(cancelled, Appointment):
        return ok(_to_response(cancelled), message="Appointment cancelled successfully")
    if isinstance(cancelled, dict):
        return ok(_to_response(cancelled), message="Appointment cancelled successfully")

    db.refresh(appointment)
    if (appointment.status or "").lower() == "cancelled":
        return ok(_to_response(appointment), message="Appointment cancelled successfully")
    appointment = _apply_cancel(db, appointment)
    return ok(_to_response(appointment), message="Appointment cancelled successfully")
