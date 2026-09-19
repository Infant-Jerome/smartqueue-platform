"""Queue model - live-queue row derived from an Appointment."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import relationship

from app.db.base import Base


class Queue(Base):
    __tablename__ = "queue"

    queue_id = Column(Integer, primary_key=True, autoincrement=True)
    appointment_id = Column(
        Integer,
        ForeignKey("appointments.appointment_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    salon_id = Column(
        Integer,
        ForeignKey("salons.salon_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    barber_id = Column(
        Integer,
        ForeignKey("barbers.barber_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    queue_position = Column(Integer, nullable=False)
    joined_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    estimated_wait_minutes = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, default="waiting")
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        CheckConstraint("queue_position >= 1", name="ck_queue_position_positive"),
        Index("ix_queue_salon", "salon_id"),
        Index("ix_queue_barber", "barber_id"),
        Index("ix_queue_position", "queue_position"),
        Index("ix_queue_status", "status"),
        Index("ix_queue_status_position", "status", "queue_position"),
    )

    appointment = relationship("Appointment", back_populates="queue")
    salon = relationship("Salon", back_populates="queue_entries")
    barber = relationship("Barber", back_populates="queue_entries")
