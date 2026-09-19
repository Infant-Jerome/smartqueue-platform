"""Notification history routes (N1-Core, Phase 5B).

History GET only — there is NO send endpoint. Authz: admin sees all,
customers see only their own rows, every other role gets 403.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.response import ok
from app.schemas.schemas import ApiResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def _role_of(user) -> str:
    role = getattr(user, "role", "")
    return str(getattr(role, "value", role) or "").strip().lower()


def _row_to_dict(row) -> dict:
    created = getattr(row, "created_at", None)
    try:
        created_iso = created.isoformat() if hasattr(created, "isoformat") else None
    except Exception:
        created_iso = None
    # N2 durable columns: DB ``type`` is exposed as ``notification_type``,
    # message copy lives in ``template_ref``/rendered body fallback.
    ntype = getattr(row, "notification_type", None)
    if ntype is None:
        ntype = getattr(row, "type", "")
    subject = getattr(row, "subject", None)
    if subject is None:
        subject = getattr(row, "template_ref", None)
    return {
        "notification_id": getattr(row, "notification_id", None),
        "user_id": getattr(row, "user_id", None),
        "appointment_id": getattr(row, "appointment_id", None),
        "channel": str(getattr(row, "channel", "") or ""),
        "type": str(ntype or ""),
        "subject": subject,
        "body": str(getattr(row, "body", "") or ""),
        "status": str(getattr(row, "status", "") or "PENDING"),
        "attempts": int(getattr(row, "attempts", 0) or 0),
        "created_at": created_iso,
    }


def _read_db_history(db: Session):
    """Return persisted rows, or None when the table/model is unavailable."""
    try:
        from app.notifications.models import Notification  # N2 durable model

        return db.query(Notification).order_by(Notification.notification_id.desc()).all()
    except Exception:
        logger.debug("notifications: DB history unavailable; outbox fallback", exc_info=False)
        return None


@router.get("", response_model=ApiResponse)
def list_notifications(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    role = _role_of(current_user)
    if role == "admin":
        pass
    elif role == "customer":
        pass
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    rows = _read_db_history(db)
    if rows is not None:
        items = [_row_to_dict(r) for r in rows]
    else:
        from app.notifications.service import OUTBOX

        items = [dict(r) for r in reversed(OUTBOX)]

    if role == "customer":
        uid = getattr(current_user, "user_id", None)
        items = [i for i in items if i.get("user_id") == uid]

    return ok(items[offset : offset + limit])
