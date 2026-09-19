"""Appointment model - central booking record linking customer to barber + service."""

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


class Appointment(Base):
    __tablename__ = "appointments"

    appointment_id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(
        Integer,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
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
    service_id = Column(
        Integer,
        ForeignKey("services.service_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    appointment_date = Column(Date, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    status = Column(String(20), nullable=False, default="booked")
    booking_type = Column(String(20), nullable=False, default="online")
    # Phase 5C SAWTE: measured wall-clock service time in whole minutes.
    # Smallest justified change: ONE nullable column on appointments only.
    # Why here (not history deltas / Queue.updated_at): history rows are
    # transient lifecycle stamps (retries/replays can duplicate them, and
    # deriving durations from deltas is fragile), and Queue.updated_at is
    # overwritten on every recompute/transition so it cannot hold a stable
    # measurement. A nullable column keeps old rows valid (NULL = unknown,
    # estimator falls back to Service.duration_minutes) and gives S2 a
    # single durable field to write on complete via
    # services.sawte.compute_actual_minutes.
    actual_duration_minutes = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        CheckConstraint("start_time < end_time", name="ck_appointment_time_range"),
        Index("ix_appointment_customer", "customer_id"),
        Index("ix_appointment_salon", "salon_id"),
        Index("ix_appointment_barber", "barber_id"),
        Index("ix_appointment_service", "service_id"),
        Index("ix_appointment_barber_date", "barber_id", "appointment_date"),
        Index("ix_appointment_status", "status"),
    )

    user = relationship(
        "User", back_populates="appointments", foreign_keys=[customer_id]
    )
    salon = relationship("Salon", back_populates="appointments")
    barber = relationship("Barber", back_populates="appointments")
    service = relationship("Service", back_populates="appointments")

    # Lifecycle-derived rows: deleting an appointment removes its queue
    # entry and history. Only cascade that destroys rows.
    queue = relationship(
        "Queue",
        back_populates="appointment",
        uselist=False,
        cascade="all, delete-orphan",
    )
    status_history = relationship(
        "AppointmentStatusHistory",
        back_populates="appointment",
        cascade="all, delete-orphan",
        order_by="AppointmentStatusHistory.changed_at",
    )
