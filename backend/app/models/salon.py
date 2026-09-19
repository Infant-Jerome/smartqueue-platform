"""Salon model - single-salon record that owns barbers and services."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text, Time
from sqlalchemy.orm import relationship

from app.db.base import Base


class Salon(Base):
    __tablename__ = "salons"

    salon_id = Column(Integer, primary_key=True, autoincrement=True)

    name = Column(String(150), nullable=False)
    address = Column(Text, nullable=True)
    phone = Column(String(20), nullable=True)
    opening_time = Column(Time, nullable=True)
    closing_time = Column(Time, nullable=True)
    status = Column(String(20), nullable=False, default="active")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # No delete cascades here: deleting a salon must not wipe history.
    barbers = relationship("Barber", back_populates="salon")
    services = relationship("Service", back_populates="salon")
    appointments = relationship("Appointment", back_populates="salon")
    queue_entries = relationship("Queue", back_populates="salon")

    def __repr__(self) -> str:
        return f"<Salon salon_id={self.salon_id} name={self.name!r}>"
