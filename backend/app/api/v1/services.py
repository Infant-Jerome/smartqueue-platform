from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.response import ok
from app.models import Service, User
from app.schemas.schemas import ServiceCreate, ServiceUpdate, ServiceResponse, ApiResponse
from app.api.deps import require_role

router = APIRouter()


@router.get("", response_model=ApiResponse)
def list_services(db: Session = Depends(get_db)):
    services = db.query(Service).filter(Service.status == "active").all()
    return ok([ServiceResponse.model_validate(s) for s in services])


@router.get("/{service_id}", response_model=ApiResponse)
def get_service(service_id: int, db: Session = Depends(get_db)):
    service = db.query(Service).filter(Service.service_id == service_id).first()
    if not service:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")
    return ok(ServiceResponse.model_validate(service))


@router.post("", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
def create_service(
    service_data: ServiceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    service = Service(
        service_name=service_data.service_name,
        description=service_data.description,
        duration_minutes=service_data.duration_minutes,
        price=service_data.price,
        status=service_data.status or "active",
        salon_id=service_data.salon_id,
    )
    db.add(service)
    db.commit()
    db.refresh(service)
    return ok(ServiceResponse.model_validate(service))


@router.put("/{service_id}", response_model=ApiResponse)
def update_service(
    service_id: int,
    service_data: ServiceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    service = db.query(Service).filter(Service.service_id == service_id).first()
    if not service:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")

    update_data = service_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(service, field, value)

    db.commit()
    db.refresh(service)
    return ok(ServiceResponse.model_validate(service))


@router.delete("/{service_id}", response_model=ApiResponse)
def delete_service(
    service_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    service = db.query(Service).filter(Service.service_id == service_id).first()
    if not service:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")

    db.delete(service)
    db.commit()
    return ok(None, message="Service deleted successfully")
