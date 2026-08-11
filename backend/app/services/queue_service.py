from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.models import Appointment, QueueEntry, Service, User


def list_active_entries(db: Session):
    return (
        db.query(QueueEntry)
        .filter(QueueEntry.status.in_(["waiting", "serving"]))
        .order_by(QueueEntry.queue_number.asc())
        .all()
    )


def get_my_position(db: Session, user: User) -> dict:
    my_appointment = (
        db.query(Appointment)
        .filter(
            Appointment.user_id == user.id,
            Appointment.status.in_(["booked", "waiting", "serving"]),
        )
        .order_by(Appointment.created_at.desc())
        .first()
    )
    if not my_appointment:
        return {"has_queue": False, "message": "No active appointment"}

    queue_entry = (
        db.query(QueueEntry)
        .filter(QueueEntry.appointment_id == my_appointment.id)
        .first()
    )
    if not queue_entry:
        return {"has_queue": False, "message": "No queue entry found"}

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
    service = (
        db.query(Service).filter(Service.id == my_appointment.service_id).first()
    )
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


def _get_entry(db: Session, entry_id: int) -> QueueEntry:
    entry = db.query(QueueEntry).filter(QueueEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Queue entry not found",
        )
    return entry


def _sync_appointment_status(db: Session, entry: QueueEntry, entry_status: str) -> None:
    appointment = (
        db.query(Appointment).filter(Appointment.id == entry.appointment_id).first()
    )
    if appointment:
        appointment.status = entry_status


def update_queue_entry(db: Session, entry_id: int, entry_status: str) -> QueueEntry:
    entry = _get_entry(db, entry_id)
    entry.status = entry_status
    _sync_appointment_status(db, entry, entry_status)
    db.commit()
    db.refresh(entry)
    return entry


def serve_customer(db: Session, entry_id: int) -> QueueEntry:
    entry = _get_entry(db, entry_id)
    if entry.status != "waiting":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Entry is not in waiting status",
        )

    entry.status = "serving"
    _sync_appointment_status(db, entry, "serving")
    db.commit()
    db.refresh(entry)
    return entry


def complete_customer(db: Session, entry_id: int) -> QueueEntry:
    entry = _get_entry(db, entry_id)
    entry.status = "completed"
    _sync_appointment_status(db, entry, "completed")
    db.commit()
    db.refresh(entry)
    return entry