"""AppointmentStatusHistory model - append-only lifecycle log."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship

from app.db.base import Base


class AppointmentStatusHistory(Base):
    __tablename__ = "appointment_status_history"

    history_id = Column(Integer, primary_key=True, autoincrement=True)
    appointment_id = Column(
        Integer,
        ForeignKey("appointments.appointment_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    old_status = Column(String(20), nullable=True)
    new_status = Column(String(20), nullable=False)
    changed_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_status_history_appointment", "appointment_id"),
        Index("ix_status_history_changed_at", "changed_at"),
    )

    appointment = relationship("Appointment", back_populates="status_history")
