"""Model package exports - eager imports so Base.metadata is complete."""

from app.models.appointment import Appointment
from app.models.availability import BarberAvailability
from app.models.barber import Barber
from app.models.password_reset import PasswordResetToken
from app.models.queue import Queue
from app.models.salon import Salon
from app.models.service import Service
from app.models.status_history import AppointmentStatusHistory
from app.models.user import User, UserRole
# N2-Persist registration: importing here puts ``notifications`` on the
# canonical Base.metadata so Alembic (via ``import app.models``) sees it.
from app.notifications.models import Notification

__all__ = [
    "User",
    "UserRole",
    "Salon",
    "Barber",
    "Service",
    "BarberAvailability",
    "Appointment",
    "Queue",
    "PasswordResetToken",
    "AppointmentStatusHistory",
    "Notification",
]
