"""BarberAvailability model - daily working windows per barber."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
)
from sqlalchemy.orm import relationship

from app.db.base import Base


class BarberAvailability(Base):
    __tablename__ = "barber_availability"

    availability_id = Column(Integer, primary_key=True, autoincrement=True)
    barber_id = Column(
        Integer,
        ForeignKey("barbers.barber_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    date = Column(Date, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    status = Column(String(20), nullable=False, default="available")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        CheckConstraint("start_time < end_time", name="ck_availability_time_range"),
        Index("ix_availability_barber_date", "barber_id", "date"),
    )

    barber = relationship("Barber", back_populates="availability")
