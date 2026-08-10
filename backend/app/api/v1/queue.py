from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.core.database import get_db
from app.models.models import QueueEntry, Appointment, Service, User
from app.schemas.schemas import QueueResponse, QueueUpdate, MessageResponse, AppointmentResponse
from app.api.deps import get_current_user, require_role

router = APIRouter()


@router.get("", response_model=list[QueueResponse])
def list_queue(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "staff")),
):
    entries = (
        db.query(QueueEntry)
        .filter(QueueEntry.status.in_(["waiting", "serving"]))
        .order_by(QueueEntry.queue_number.asc())
        .all()
    )
    return [QueueResponse.model_validate(e) for e in entries]


@router.get("/my-position", response_model=dict)
def get_my_position(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    my_appointment = (
        db.query(Appointment)
        .filter(
            Appointment.user_id == current_user.id,
            Appointment.status.in_(["booked", "waiting", "serving"]),
        )
        .order_by(Appointment.created_at.desc())
        .first()
    )
    if not my_appointment:
        return {"has_queue": False, "message": "No active appointment"}

    queue_entry = db.query(QueueEntry).filter(QueueEntry.appointment_id == my_appointment.id).first()
    if not queue_entry:
        return {"has_queue": False, "message": "No queue entry found"}

    from sqlalchemy import func

    people_ahead = (
        db.query(QueueEntry)
        .filter(
            QueueEntry.status.in_(["waiting"]),
            QueueEntry.queue_number < queue_entry.queue_number,
            func.date(QueueEntry.created_at) == queue_entry.created_at.date(),
        )
        .count()
    )

    currently_serving = (
        db.query(QueueEntry)
        .filter(
            QueueEntry.status == "serving",
            func.date(QueueEntry.created_at) == queue_entry.created_at.date(),
        )
        .first()
    )

    avg_duration = 20
    service = db.query(Service).filter(Service.id == my_appointment.service_id).first()
    if service:
        avg_duration = service.duration

    estimated_wait = people_ahead * avg_duration

    return {
        "has_queue": True,
        "queue_number": queue_entry.queue_number,
        "status": queue_entry.status,
        "people_ahead": people_ahead,
        "estimated_wait_minutes": estimated_wait,
        "currently_serving": currently_serving.queue_number if currently_serving else None,
        "appointment_status": my_appointment.status,
    }


@router.put("/{entry_id}", response_model=QueueResponse)
def update_queue_entry(
    entry_id: int,
    data: QueueUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "staff")),
):
    entry = db.query(QueueEntry).filter(QueueEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Queue entry not found")

    entry.status = data.status

    appointment = db.query(Appointment).filter(Appointment.id == entry.appointment_id).first()
    if appointment:
        appointment.status = data.status

    db.commit()
    db.refresh(entry)
    return QueueResponse.model_validate(entry)


@router.post("/{entry_id}/serve", response_model=QueueResponse)
def serve_customer(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "staff")),
):
    entry = db.query(QueueEntry).filter(QueueEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Queue entry not found")

    if entry.status != "waiting":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Entry is not in waiting status")

    entry.status = "serving"
    appointment = db.query(Appointment).filter(Appointment.id == entry.appointment_id).first()
    if appointment:
        appointment.status = "serving"

    db.commit()
    db.refresh(entry)
    return QueueResponse.model_validate(entry)


@router.post("/{entry_id}/complete", response_model=QueueResponse)
def complete_customer(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "staff")),
):
    entry = db.query(QueueEntry).filter(QueueEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Queue entry not found")

    entry.status = "completed"
    appointment = db.query(Appointment).filter(Appointment.id == entry.appointment_id).first()
    if appointment:
        appointment.status = "completed"

    db.commit()
    db.refresh(entry)
    return QueueResponse.model_validate(entry)
