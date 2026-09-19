"""User model - login credentials, role and basic profile info."""

import enum
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, Integer, String
from sqlalchemy.orm import relationship

from app.db.base import Base


class UserRole(str, enum.Enum):
    """Controlled set of user roles (persisted as plain strings).

    Canonical Phase 2: customer, barber, receptionist, admin.
    STAFF is kept as an alias of receptionist for backwards
    compatibility (VARCHAR native_enum=False so no migration needed).
    """

    CUSTOMER = "customer"
    BARBER = "barber"
    RECEPTIONIST = "receptionist"
    ADMIN = "admin"
    STAFF = "staff"


class User(Base):
    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True, autoincrement=True)

    name = Column(String(100), nullable=False)
    email = Column(String(255), nullable=False, unique=True, index=True)
    phone = Column(String(20), nullable=True)
    # Never plaintext: always a hash written via app.core.security.
    password_hash = Column(String(255), nullable=False)
    role = Column(
        Enum(UserRole, native_enum=False, length=20, validate_strings=True),
        nullable=False,
        default=UserRole.CUSTOMER,
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    appointments = relationship(
        "Appointment",
        back_populates="user",
        foreign_keys="Appointment.customer_id",
    )
    # Optional 1-1 link for users whose role is barber.
    barber_profile = relationship(
        "Barber",
        back_populates="user",
        foreign_keys="Barber.user_id",
        uselist=False,
    )

    def __repr__(self) -> str:
        return f"<User user_id={self.user_id} email={self.email!r} role={self.role}>"
