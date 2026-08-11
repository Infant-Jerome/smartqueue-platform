from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.response import ok
from app.core.security import hash_password, verify_password, create_access_token
from app.models.models import User
from app.schemas.schemas import (
    UserCreate, UserLogin, UserResponse, TokenResponse, ApiResponse,
)
from app.api.deps import get_current_user

router = APIRouter()


@router.post("/register", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == user_data.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    user = User(
        name=user_data.name,
        email=user_data.email,
        password_hash=hash_password(user_data.password),
        phone=user_data.phone,
        role="customer",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(data={"sub": str(user.id), "role": user.role})
    return ok(
        TokenResponse(
            access_token=token,
            user=UserResponse.model_validate(user),
        ),
        message="Registered successfully",
    )


@router.post("/login", response_model=ApiResponse)
def login(credentials: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == credentials.email).first()
    if not user or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = create_access_token(data={"sub": str(user.id), "role": user.role})
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