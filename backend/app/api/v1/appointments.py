from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.response import ok
from app.models.models import User
from app.schemas.schemas import (
    AppointmentCreate, AppointmentUpdate, AppointmentResponse, ApiResponse,
)
from app.api.deps import get_current_user, require_role
from app.services import appointments_service

router = APIRouter()


@router.get("", response_model=ApiResponse)
def list_appointments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    appointments = appointments_service.list_appointments(db, current_user)
    return ok([AppointmentResponse.model_validate(a) for a in appointments])


@router.get("/{appointment_id}", response_model=ApiResponse)
def get_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    appointment = appointments_service.get_appointment(db, appointment_id, current_user)
    return ok(AppointmentResponse.model_validate(appointment))


@router.post("", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
def create_appointment(
    data: AppointmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    appointment = appointments_service.create_appointment(db, current_user, data)
    return ok(AppointmentResponse.model_validate(appointment))


@router.put("/{appointment_id}", response_model=ApiResponse)
def update_appointment(
    appointment_id: int,
    data: AppointmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    appointment = appointments_service.update_appointment(db, appointment_id, data, current_user)
    return ok(AppointmentResponse.model_validate(appointment))


@router.delete("/{appointment_id}", response_model=ApiResponse)
def delete_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    appointments_service.delete_appointment(db, appointment_id)
    return ok(None, message="Appointment deleted successfully")