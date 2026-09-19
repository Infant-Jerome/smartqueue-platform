"""B1-Availability routes (Phase 3).

RBAC matrix (enforced via ``app.api.deps`` shim + service guards):
- POST /          : admin + staff/receptionist (any barber) + owner-barber.
                    Customer (or unauthenticated) -> 403 / 401.
- GET /           : any authenticated user (customer read-only list with
                    optional ``barber_id`` + ``date`` filters).
- GET /{id}       : any authenticated user; missing -> 404.
- PUT /{id}       : same write rule as POST (barber own-only via
                    ``Barber.user_id``; Barber A vs Barber B -> 403).
- DELETE /{id}    : admin hard-deletes; owner-barber hard-deletes own;
                    staff/receptionist deactivates (status='unavailable');
                    customer / non-owner barber -> 403.
"""

import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role
from app.core.database import get_db
from app.core.response import ok
from app.models import User
from app.schemas.availability import (
    AvailabilityCreate,
    AvailabilityResponse,
    AvailabilityUpdate,
)
from app.schemas.schemas import ApiResponse
from app.services import availability_service

router = APIRouter()

# Any of these roles may reach the write endpoints; the service layer then
# enforces owner-only for role=barber (customers never reach it -> 403 here).
_write_guard = require_role("admin", "staff", "receptionist", "barber")


def _to_response(entry) -> AvailabilityResponse:
    return AvailabilityResponse.model_validate(entry)


@router.post("", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
def create_availability(
    data: AvailabilityCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(_write_guard),
):
    entry = availability_service.create_availability(db, current_user, data)
    return ok(_to_response(entry))


@router.get("", response_model=ApiResponse)
def list_availability(
    barber_id: Optional[int] = Query(default=None, gt=0),
    date: Optional[datetime.date] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    entries = availability_service.list_availabilities(db, barber_id, date)
    return ok([_to_response(e) for e in entries])


@router.get("/{availability_id}", response_model=ApiResponse)
def get_availability(
    availability_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    entry = availability_service.get_availability_or_404(db, availability_id)
    return ok(_to_response(entry))


@router.put("/{availability_id}", response_model=ApiResponse)
def update_availability(
    availability_id: int,
    data: AvailabilityUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(_write_guard),
):
    entry = availability_service.update_availability(
        db, current_user, availability_id, data
    )
    return ok(_to_response(entry))


@router.delete("/{availability_id}", response_model=ApiResponse)
def delete_availability(
    availability_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_write_guard),
):
    entry, hard_deleted = availability_service.delete_availability(
        db, current_user, availability_id
    )
    if hard_deleted:
        return ok(None, message="Availability deleted successfully")
    return ok(_to_response(entry), message="Availability deactivated")
