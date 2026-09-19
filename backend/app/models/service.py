"""Service model - sellable salon service with duration/price guards."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.db.base import Base


class Service(Base):
    __tablename__ = "services"

    service_id = Column(Integer, primary_key=True, autoincrement=True)

    salon_id = Column(
        Integer,
        ForeignKey("salons.salon_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    service_name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    duration_minutes = Column(Integer, nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
    status = Column(String(20), nullable=False, default="active")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    salon = relationship("Salon", back_populates="services")
    # Deliberately NO delete cascade: removing a service must not destroy
    # appointment/queue history.
    appointments = relationship("Appointment", back_populates="service")

    __table_args__ = (
        CheckConstraint("duration_minutes > 0", name="ck_services_duration_positive"),
        CheckConstraint("price >= 0", name="ck_services_price_non_negative"),
    )

    def __repr__(self) -> str:
        return f"<Service service_id={self.service_id} name={self.service_name!r}>"
