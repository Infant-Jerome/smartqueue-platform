from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, Numeric, Time, Date, UniqueConstraint
)
from sqlalchemy.orm import relationship
from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    phone = Column(String(20), nullable=True)
    role = Column(String(20), nullable=False, default="customer")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    appointments = relationship("Appointment", back_populates="user", cascade="all, delete-orphan")


class Barber(Base):
    __tablename__ = "barbers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    specialization = Column(String(255), nullable=True)
    phone = Column(String(20), nullable=True)
    status = Column(String(20), nullable=False, default="available")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    appointments = relationship("Appointment", back_populates="barber", cascade="all, delete-orphan")


class Service(Base):
    __tablename__ = "services"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    duration = Column(Integer, nullable=False, comment="Duration in minutes")
    price = Column(Numeric(10, 2), nullable=False)
    status = Column(String(20), nullable=False, default="active")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    appointments = relationship("Appointment", back_populates="service", cascade="all, delete-orphan")


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    barber_id = Column(Integer, ForeignKey("barbers.id", ondelete="CASCADE"), nullable=False)
    service_id = Column(Integer, ForeignKey("services.id", ondelete="CASCADE"), nullable=False)
    appointment_date = Column(Date, nullable=False)
    appointment_time = Column(Time, nullable=False)
    status = Column(String(20), nullable=False, default="booked")
    queue_number = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="appointments")
    barber = relationship("Barber", back_populates="appointments")
    service = relationship("Service", back_populates="appointments")
    queue = relationship("QueueEntry", back_populates="appointment", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("barber_id", "appointment_date", "appointment_time", name="uq_barber_slot"),
    )


class QueueEntry(Base):
    __tablename__ = "queue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    appointment_id = Column(Integer, ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False, unique=True)
    queue_number = Column(Integer, nullable=False)
    estimated_wait_time = Column(Integer, nullable=True, comment="Estimated wait in minutes")
    status = Column(String(20), nullable=False, default="waiting")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    appointment = relationship("Appointment", back_populates="queue")
