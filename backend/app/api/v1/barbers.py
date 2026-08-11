from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.response import ok
from app.models.models import Barber, User
from app.schemas.schemas import BarberCreate, BarberUpdate, BarberResponse, ApiResponse
from app.api.deps import require_role

router = APIRouter()


@router.get("", response_model=ApiResponse)
def list_barbers(db: Session = Depends(get_db)):
    barbers = db.query(Barber).filter(Barber.status != "inactive").all()
    return ok([BarberResponse.model_validate(b) for b in barbers])


@router.get("/{barber_id}", response_model=ApiResponse)
def get_barber(barber_id: int, db: Session = Depends(get_db)):
    barber = db.query(Barber).filter(Barber.id == barber_id).first()
    if not barber:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Barber not found")
    return ok(BarberResponse.model_validate(barber))


@router.post("", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
def create_barber(
    barber_data: BarberCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    barber = Barber(
        name=barber_data.name,
        specialization=barber_data.specialization,
        phone=barber_data.phone,
        status=barber_data.status or "available",
    )
    db.add(barber)
    db.commit()
    db.refresh(barber)
    return ok(BarberResponse.model_validate(barber))


@router.put("/{barber_id}", response_model=ApiResponse)
def update_barber(
    barber_id: int,
    barber_data: BarberUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    barber = db.query(Barber).filter(Barber.id == barber_id).first()
    if not barber:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Barber not found")

    update_data = barber_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(barber, field, value)

    db.commit()
    db.refresh(barber)
    return ok(BarberResponse.model_validate(barber))


@router.delete("/{barber_id}", response_model=ApiResponse)
def delete_barber(
    barber_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    barber = db.query(Barber).filter(Barber.id == barber_id).first()
    if not barber:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Barber not found")

    db.delete(barber)
    db.commit()
    return ok(None, message="Barber deleted successfully")