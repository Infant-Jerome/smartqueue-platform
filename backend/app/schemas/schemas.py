from pydantic import BaseModel, EmailStr, Field
from datetime import datetime, date, time
from typing import Optional


class UserCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: str = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=6)
    phone: Optional[str] = None


class UserLogin(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    phone: Optional[str] = None
    role: str
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class ServiceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    duration: int = Field(..., gt=0, comment="Duration in minutes")
    price: float = Field(..., gt=0)
    status: Optional[str] = "active"


class ServiceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    duration: Optional[int] = Field(None, gt=0)
    price: Optional[float] = Field(None, gt=0)
    status: Optional[str] = None


class ServiceResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    duration: int
    price: float
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class BarberCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    specialization: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = "available"


class BarberUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    specialization: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = None


class BarberResponse(BaseModel):
    id: int
    name: str
    specialization: Optional[str] = None
    phone: Optional[str] = None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class AppointmentCreate(BaseModel):
    barber_id: int
    service_id: int
    appointment_date: str = Field(..., description="Format: YYYY-MM-DD")
    appointment_time: str = Field(..., description="Format: HH:MM")


class AppointmentUpdate(BaseModel):
    status: Optional[str] = None


class AppointmentResponse(BaseModel):
    id: int
    user_id: int
    barber_id: int
    service_id: int
    appointment_date: date
    appointment_time: time
    status: str
    queue_number: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    barber: Optional[BarberResponse] = None
    service: Optional[ServiceResponse] = None

    class Config:
        from_attributes = True


class QueueResponse(BaseModel):
    id: int
    appointment_id: int
    queue_number: int
    estimated_wait_time: Optional[int] = None
    status: str
    created_at: datetime
    appointment: Optional[AppointmentResponse] = None

    class Config:
        from_attributes = True


class QueueUpdate(BaseModel):
    status: str


class MessageResponse(BaseModel):
    success: bool
    message: str
    data: Optional[dict | list | None] = None
