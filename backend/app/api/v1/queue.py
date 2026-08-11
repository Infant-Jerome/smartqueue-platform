from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.response import ok
from app.models.models import User
from app.schemas.schemas import QueueResponse, QueueUpdate, ApiResponse
from app.api.deps import get_current_user, require_role
from app.services import queue_service

router = APIRouter()


@router.get("", response_model=ApiResponse)
def list_queue(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "staff")),
):
    entries = queue_service.list_active_entries(db)
    return ok([QueueResponse.model_validate(e) for e in entries])


@router.get("/my-position", response_model=ApiResponse)
def get_my_position(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return ok(queue_service.get_my_position(db, current_user))


@router.put("/{entry_id}", response_model=ApiResponse)
def update_queue_entry(
    entry_id: int,
    data: QueueUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "staff")),
):
    entry = queue_service.update_queue_entry(db, entry_id, data.status)
    return ok(QueueResponse.model_validate(entry))


@router.post("/{entry_id}/serve", response_model=ApiResponse)
def serve_customer(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "staff")),
):
    entry = queue_service.serve_customer(db, entry_id)
    return ok(QueueResponse.model_validate(entry))


@router.post("/{entry_id}/complete", response_model=ApiResponse)
def complete_customer(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "staff")),
):
    entry = queue_service.complete_customer(db, entry_id)
    return ok(QueueResponse.model_validate(entry))