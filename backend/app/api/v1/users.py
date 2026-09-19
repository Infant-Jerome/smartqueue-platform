"""Users routes (I2-Routes Phase 2). Canonical /users prefix.

Auth router owns /auth/* (register/login/me + /auth/users/{id}/role alias).
This router owns the canonical REST paths under /users without duplicating
/auth paths: GET /users/{id} and PATCH /users/{id}/role.
All responses use the uniform ok() envelope.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role
from app.core.database import get_db
from app.core.response import ok
from app.models import User
from app.models.user import UserRole
from app.schemas.schemas import ApiResponse, RoleUpdate, UserResponse

router = APIRouter()


def _is_admin(user: User) -> bool:
    role = getattr(user.role, "value", user.role)
    return role == "admin"


@router.get("/{user_id}", response_model=ApiResponse)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    target = db.query(User).filter(User.user_id == user_id).first()
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    if target.user_id != current_user.user_id and not _is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    return ok(UserResponse.model_validate(target))


@router.patch("/{user_id}/role", response_model=ApiResponse)
def set_user_role(
    user_id: int,
    payload: RoleUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin", UserRole.ADMIN)),
):
    target = db.query(User).filter(User.user_id == user_id).first()
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    target.role = payload.role
    db.add(target)
    db.commit()
    db.refresh(target)
    return ok(UserResponse.model_validate(target), message="Role updated")
