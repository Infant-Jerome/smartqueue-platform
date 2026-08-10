from datetime import datetime, date, time
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.core.database import get_db
from app.models.models import Appointment, Barber, Service, QueueEntry, User
from app.schemas.schemas import AppointmentCreate, AppointmentUpdate, AppointmentResponse, MessageResponse
from app.api.deps import get_current_user, require_role

router = APIRouter()


@router.get("", response_model=list[AppointmentResponse])
def list_appointments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role in ("admin", "staff"):
        appointments = db.query(Appointment).order_by(Appointment.created_at.desc()).all()
    else:
        appointments = (
            db.query(Appointment)
            .filter(Appointment.user_id == current_user.id)
            .order_by(Appointment.created_at.desc())
            .all()
        )
    return [AppointmentResponse.model_validate(a) for a in appointments]


@router.get("/{appointment_id}", response_model=AppointmentResponse)
def get_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appointment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")

    if current_user.role == "customer" and appointment.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return AppointmentResponse.model_validate(appointment)


@router.post("", response_model=AppointmentResponse, status_code=status.HTTP_201_CREATED)
def create_appointment(
    data: AppointmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    barber = db.query(Barber).filter(Barber.id == data.barber_id).first()
    if not barber:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Barber not found")
    if barber.status == "inactive":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Barber is not available")

    service = db.query(Service).filter(Service.id == data.service_id).first()
    if not service:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")
    if service.status == "inactive":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Service is not available")

    try:
        appt_date = date.fromisoformat(data.appointment_date)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date format. Use YYYY-MM-DD")

    if appt_date < date.today():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot book appointments in the past")

    try:
        appt_time = time.fromisoformat(data.appointment_time)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid time format. Use HH:MM")

    existing = (
        db.query(Appointment)
        .filter(
            Appointment.barber_id == data.barber_id,
            Appointment.appointment_date == appt_date,
            Appointment.appointment_time == appt_time,
            Appointment.status.notin_(["cancelled", "no_show"]),
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Sorry, this time slot was just booked by another customer. Please select another time.",
        )

    conflicting = (
        db.query(Appointment)
        .filter(
            Appointment.user_id == current_user.id,
            Appointment.appointment_date == appt_date,
            Appointment.appointment_time == appt_time,
            Appointment.status.notin_(["cancelled", "no_show"]),
        )
        .first()
    )
    if conflicting:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have an appointment at this time",
        )

    today_str = appt_date.isoformat()
    last_queue = (
        db.query(QueueEntry)
        .join(Appointment)
        .filter(Appointment.appointment_date == appt_date)
        .order_by(QueueEntry.queue_number.desc())
        .first()
    )
    next_queue_number = (last_queue.queue_number + 1) if last_queue else 1

    appointment = Appointment(
        user_id=current_user.id,
        barber_id=data.barber_id,
        service_id=data.service_id,
        appointment_date=appt_date,
        appointment_time=appt_time,
        status="booked",
        queue_number=next_queue_number,
    )
    db.add(appointment)
    db.flush()

    queue_entry = QueueEntry(
        appointment_id=appointment.id,
        queue_number=next_queue_number,
        estimated_wait_time=service.duration,
        status="waiting",
    )
    db.add(queue_entry)
    db.commit()
    db.refresh(appointment)

    return AppointmentResponse.model_validate(appointment)


@router.put("/{appointment_id}", response_model=AppointmentResponse)
def update_appointment(
    appointment_id: int,
    data: AppointmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appointment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")

    if current_user.role == "customer":
        if appointment.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        if data.status not in ("cancelled", None):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Customers can only cancel appointments")

    if data.status:
        appointment.status = data.status

    db.commit()
    db.refresh(appointment)
    return AppointmentResponse.model_validate(appointment)


@router.delete("/{appointment_id}", response_model=MessageResponse)
def delete_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appointment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")

    db.delete(appointment)
    db.commit()
    return MessageResponse(success=True, message="Appointment deleted successfully")
