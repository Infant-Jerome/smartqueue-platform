"""Barber model - staff profile optionally linked to a login user + salon."""

from datetime import datetime

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.db.base import Base


class Barber(Base):
    __tablename__ = "barbers"

    barber_id = Column(Integer, primary_key=True, autoincrement=True)

    # Optional link to the login account (role='barber'). Nullable so
    # legacy rows and admin-created barbers without accounts keep working.
    user_id = Column(
        Integer,
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    salon_id = Column(
        Integer,
        ForeignKey("salons.salon_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    experience_years = Column(Integer, nullable=False, default=0)
    name = Column(String(100), nullable=False)
    specialization = Column(String(255), nullable=True)
    phone = Column(String(20), nullable=True)
    availability_status = Column(String(20), nullable=False, default="available")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    user = relationship(
        "User", back_populates="barber_profile", foreign_keys=[user_id]
    )
    salon = relationship("Salon", back_populates="barbers")
    availability = relationship("BarberAvailability", back_populates="barber")
    # Deliberately NO delete cascade: removing a barber must not destroy
    # appointment/queue history.
    appointments = relationship("Appointment", back_populates="barber")
    queue_entries = relationship("Queue", back_populates="barber")

    __table_args__ = (
        CheckConstraint(
            "experience_years >= 0", name="ck_barbers_experience_non_negative"
        ),
    )

    def __repr__(self) -> str:
        return f"<Barber barber_id={self.barber_id} name={self.name!r}>"
