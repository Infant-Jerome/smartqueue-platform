"""Auth routes (I2-Routes Phase 2). Envelope: ok() everywhere."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role
from app.core.database import get_db
from app.core.response import ok
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User
from app.models.user import UserRole
from app.schemas.schemas import (
    ApiResponse,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    RoleUpdate,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
    UserUpdate,
    VerifyResetOtpRequest,
)

router = APIRouter()


def _role_str(role) -> str:
    return getattr(role, "value", role) if role is not None else role


def _token_for(user: User) -> str:
    return create_access_token(
        data={"sub": str(user.user_id), "role": str(_role_str(user.role))}
    )


@router.post("/register", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    email = user_data.email.strip().lower() if isinstance(user_data.email, str) else user_data.email
    existing = db.query(User).filter(func.lower(User.email) == email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = User(
        name=user_data.name,
        email=email,
        password_hash=hash_password(user_data.password),
        phone=user_data.phone,
        role=UserRole.CUSTOMER,  # forced; client role never accepted (extra=forbid)
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = _token_for(user)
    return ok(
        TokenResponse(
            access_token=token,
            user=UserResponse.model_validate(user),
        ),
        message="Registered successfully",
    )


@router.post("/login", response_model=ApiResponse)
def login(credentials: UserLogin, db: Session = Depends(get_db)):
    email = credentials.email.strip().lower() if isinstance(credentials.email, str) else credentials.email
    user = db.query(User).filter(func.lower(User.email) == email).first()
    if not user or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = _token_for(user)
    return ok(
        TokenResponse(
            access_token=token,
            user=UserResponse.model_validate(user),
        ),
        message="Login successful",
    )


@router.get("/me", response_model=ApiResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return ok(UserResponse.model_validate(current_user))


@router.patch("/me", response_model=ApiResponse)
@router.put("/me", response_model=ApiResponse)
def update_me(
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Self-editable fields only (name/phone); role/user_id never accepted.
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        current_user.name = data["name"]
    if "phone" in data:
        current_user.phone = data["phone"]
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return ok(UserResponse.model_validate(current_user), message="Profile updated")


@router.patch("/users/{user_id}/role", response_model=ApiResponse)
def update_user_role(
    user_id: int,
    payload: RoleUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin", UserRole.ADMIN)),
):
    # require_role already 403s non-admins (blocks self-escalation).
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


@router.post("/forgot-password", response_model=ApiResponse)
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Issue an OTP email. Reply is always generic (no enumeration)."""
    from app.services import password_reset_service as prs

    try:
        prs.request_reset(db, payload.email)
    except prs.ResendCooldownError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)
        )
    except prs.EmailDeliveryError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )
    return ok(None, message=prs.GENERIC_FORGOT_MESSAGE)


@router.post("/verify-reset-otp", response_model=ApiResponse)
def verify_reset_otp(payload: VerifyResetOtpRequest, db: Session = Depends(get_db)):
    """Verify the OTP; return a short-lived reset authorization token."""
    from app.services import password_reset_service as prs

    try:
        reset_token = prs.verify_otp(db, payload.email, payload.otp)
    except prs.TooManyAttemptsError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)
        )
    except (prs.InvalidOtpError, prs.ExpiredOtpError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    return ok({"reset_token": reset_token}, message="Code verified.")


@router.post("/reset-password", response_model=ApiResponse)
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Consume the reset token and set the new password hash."""
    from app.services import password_reset_service as prs

    try:
        prs.reset_password(db, payload.reset_token, payload.new_password)
    except prs.InvalidResetTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        )
    return ok(None, message="Password reset successfully.")
