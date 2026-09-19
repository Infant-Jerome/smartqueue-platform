"""Deprecated re-export shim.

Canonical models live in per-entity modules
(user/salon/barber/service/availability/appointment/queue/status_history)
on ``app.db.base.Base``. This module defines NO tables; it only re-exports
for backwards compatibility (``from app.models.models import X``).

.. deprecated::
    Import from ``app.models`` instead.
"""

import warnings

from app.db.base import Base
from app.models.appointment import Appointment
from app.models.availability import BarberAvailability
from app.models.barber import Barber
from app.models.queue import Queue
from app.models.salon import Salon
from app.models.service import Service
from app.models.status_history import AppointmentStatusHistory
from app.models.user import User, UserRole

# Legacy alias: pre-1.1 code used QueueEntry for the ``queue`` table.
QueueEntry = Queue

__all__ = [
    "Base",
    "User",
    "UserRole",
    "Salon",
    "Barber",
    "Service",
    "BarberAvailability",
    "Appointment",
    "Queue",
    "QueueEntry",
    "AppointmentStatusHistory",
]

warnings.warn(
    "app.models.models is deprecated; import from app.models instead.",
    DeprecationWarning,
    stacklevel=2,
)
