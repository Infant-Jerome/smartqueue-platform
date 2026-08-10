from fastapi import APIRouter
from app.api.v1 import auth, services, barbers, appointments, queue

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(services.router, prefix="/services", tags=["Services"])
api_router.include_router(barbers.router, prefix="/barbers", tags=["Barbers"])
api_router.include_router(appointments.router, prefix="/appointments", tags=["Appointments"])
api_router.include_router(queue.router, prefix="/queue", tags=["Queue"])
