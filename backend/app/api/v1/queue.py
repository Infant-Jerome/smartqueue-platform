"""Queue routes (Q2-Routes, SmartQueue Phase 4).

Thin HTTP layer over the queue engine (``app.services.queue_service``).
Owns request/response shape, authz scoping and status codes; queue math
and persistence rules live in the service layer.

Preserved: GET / (list), GET /my-position, PUT /{id},
POST /{id}/serve, POST /{id}/complete.
Added: POST /serve-next, POST /{id}/skip, GET /current.
Envelope: ok(). No 500 on empty queue (404 for serve-next with no
waiting entries, 200+null for /current with nobody serving).
"""

from datetime import date as _date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.response import ok
from app.models import Appointment, Barber, Queue, User
from app.schemas.schemas import (
    ApiResponse,
    QueueResponse,
    QueueUpdate,
    ServeNextRequest,
)
from app.services import queue_service

router = APIRouter()

_STAFF_ROLES = frozenset({"staff", "receptionist"})
_ACTIVE_QUEUE_STATUSES = ("waiting", "serving", "in_progress")
_SERVING_STATUSES = ("serving", "in_progress")


def _role_of(user: User) -> str:
    role = getattr(user, "role", "")
    value = getattr(role, "value", role)
    return str(value or "").strip().lower()


def _barber_profile(db: Session, user: User) -> Optional[Barber]:
    return db.query(Barber).filter(Barber.user_id == user.user_id).first()


def _to_response(entry: Queue, db: Session | None = None) -> QueueResponse:
    """Serialize a queue row; attach transient SAWTE confidence (Phase 5C,
    S2-Integrate) when a session is available -- verbatim, never persisted.
    The confidence path never raises so serialization cannot break REST."""
    resp = QueueResponse.model_validate(entry)
    if db is not None:
        try:
            resp.confidence = queue_service.get_confidence_for_entry(db, entry)
        except Exception:
            pass
    return resp


def _get_or_404(db: Session, entry_id: int) -> Queue:
    entry = db.query(Queue).filter(Queue.queue_id == entry_id).first()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Queue entry not found"
        )
    return entry


def _require_operational(user: User) -> str:
    """Customers cannot run operational queue actions (403)."""
    role = _role_of(user)
    if role == "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    return role


def _require_barber_scope(db: Session, user: User, barber_id: int) -> None:
    """Barbers may only operate on their own barber row (via Barber.user_id)."""
    if _role_of(user) != "barber":
        return
    profile = _barber_profile(db, user)
    if profile is None or barber_id != profile.barber_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
        )


@router.get("", response_model=ApiResponse)
def list_queue(
    salon_id: Optional[int] = Query(default=None),
    barber_id: Optional[int] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    date: Optional[_date] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    role = _role_of(current_user)
    if role == "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    query = db.query(Queue)
    if role == "barber":
        profile = _barber_profile(db, current_user)
        if profile is None:
            return ok([])
        if barber_id is not None and barber_id != profile.barber_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
            )
        query = query.filter(Queue.barber_id == profile.barber_id)
    elif barber_id is not None:
        query = query.filter(Queue.barber_id == barber_id)
    if salon_id is not None:
        query = query.filter(Queue.salon_id == salon_id)
    if status_filter is not None:
        query = query.filter(Queue.status == status_filter)
    else:
        query = query.filter(Queue.status.in_(_ACTIVE_QUEUE_STATUSES))
    if date is not None:
        query = query.join(
            Appointment, Queue.appointment_id == Appointment.appointment_id
        ).filter(Appointment.appointment_date == date)
    entries = query.order_by(Queue.queue_position.asc()).all()
    return ok([_to_response(e, db) for e in entries])


@router.get("/my-position", response_model=ApiResponse)
def get_my_position(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = queue_service.get_my_position(db, current_user)
    if isinstance(data, dict) and data.get("has_queue"):
        data.setdefault("current_position", data.get("currently_serving"))
    return ok(data)


@router.get("/current", response_model=ApiResponse)
def get_current(
    barber_id: Optional[int] = Query(default=None),
    salon_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    role = _role_of(current_user)
    effective_barber = barber_id
    if role == "barber":
        profile = _barber_profile(db, current_user)
        if profile is None:
            return ok(None, message="No customer currently being served")
        if barber_id is not None and barber_id != profile.barber_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
            )
        effective_barber = profile.barber_id
    query = db.query(Queue).filter(Queue.status.in_(_SERVING_STATUSES))
    if effective_barber is not None:
        query = query.filter(Queue.barber_id == effective_barber)
    if salon_id is not None:
        query = query.filter(Queue.salon_id == salon_id)
    entry = query.order_by(Queue.queue_position.asc()).first()
    if entry is None:
        return ok(None, message="No customer currently being served")
    return ok(_to_response(entry, db))


@router.post("/serve-next", response_model=ApiResponse)
def serve_next(
    body: ServeNextRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    role = _require_operational(current_user)
    _require_barber_scope(db, current_user, body.barber_id)
    barber = (
        db.query(Barber).filter(Barber.barber_id == body.barber_id).first()
    )
    if barber is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Barber not found"
        )
    _ = role
    active_q = db.query(Queue).filter(
        Queue.barber_id == body.barber_id,
        Queue.status.in_(_SERVING_STATUSES),
    )
    if body.salon_id is not None:
        active_q = active_q.filter(Queue.salon_id == body.salon_id)
    if active_q.first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Barber already has a customer in service",
        )
    next_q = db.query(Queue).filter(
        Queue.barber_id == body.barber_id,
        Queue.status == "waiting",
    )
    if body.salon_id is not None:
        next_q = next_q.filter(Queue.salon_id == body.salon_id)
    nxt = next_q.order_by(Queue.queue_position.asc()).first()
    if nxt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No waiting customers in queue",
        )
    entry = queue_service.serve_customer(db, nxt.queue_id)
    return ok(_to_response(entry, db))


@router.put("/{entry_id}", response_model=ApiResponse)
def update_queue_entry(
    entry_id: int,
    data: QueueUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_operational(current_user)
    entry = _get_or_404(db, entry_id)
    _require_barber_scope(db, current_user, entry.barber_id)
    if data.status is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="status is required",
        )
    updated = queue_service.update_queue_entry(db, entry_id, data.status)
    return ok(_to_response(updated, db))


@router.post("/{entry_id}/serve", response_model=ApiResponse)
def serve_customer(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_operational(current_user)
    entry = _get_or_404(db, entry_id)
    _require_barber_scope(db, current_user, entry.barber_id)
    served = queue_service.serve_customer(db, entry_id)
    return ok(_to_response(served, db))


@router.post("/{entry_id}/complete", response_model=ApiResponse)
def complete_customer(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_operational(current_user)
    entry = _get_or_404(db, entry_id)
    _require_barber_scope(db, current_user, entry.barber_id)
    done = queue_service.complete_customer(db, entry_id)
    return ok(_to_response(done, db))


@router.post("/{entry_id}/skip", response_model=ApiResponse)
def skip_customer(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_operational(current_user)
    entry = _get_or_404(db, entry_id)
    _require_barber_scope(db, current_user, entry.barber_id)
    if entry.status != "waiting":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only waiting entries can be skipped",
        )
    skipped = queue_service.update_queue_entry(db, entry_id, "no_show")
    return ok(_to_response(skipped, db))
