"""Seed the database with sample data - DEV / DEMO ONLY, never auto-run in prod.

Run manually for local development ONLY after migrations::

  cd backend
  alembic upgrade head
  python seed.py

Demo credentials are env-controlled (SEED_ADMIN_EMAIL, SEED_ADMIN_PASSWORD,
SEED_CUSTOMER_EMAIL, SEED_CUSTOMER_PASSWORD, SEED_BARBER_EMAIL,
SEED_BARBER_PASSWORD, SEED_STAFF_EMAIL, SEED_STAFF_PASSWORD);
defaults are local-demo only.
Refuses to run when production is detected unless ALLOW_SEED=true.
Production never depends on sqlite; sqlite is a local/dev fallback only.
Never prints passwords.
Uses canonical Phase-1 models only (user_id / salon_id / barber_id /
service_id + service_name / duration_minutes / appointment_id + customer_id
+ start_time / end_time / queue_id + queue_position)."""
import sys
import os
from datetime import date, time

sys.path.insert(0, os.path.dirname(__file__))

from app.core.security import hash_password
from app.db.base import Base
from app.db.database import SessionLocal, engine
from app.models.appointment import Appointment
from app.models.availability import BarberAvailability
from app.models.barber import Barber
from app.models.queue import Queue
from app.models.salon import Salon
from app.models.service import Service
from app.models.status_history import AppointmentStatusHistory
from app.models.user import User


def _is_production() -> bool:
    if os.getenv("ALLOW_SEED", "").lower() == "true":
        return False
    env = (os.getenv("ENV", "") + " " + os.getenv("APP_ENV", "")).lower()
    if "prod" in env:
        return True
    if os.getenv("RENDER_EXTERNAL_URL") or os.getenv("RENDER"):
        return True
    return False


def seed():
    if _is_production():
        print("Refusing to seed: production environment detected (set ALLOW_SEED=true to override).")
        return
    admin_email = os.getenv("SEED_ADMIN_EMAIL", "admin@salon.com")
    admin_password = os.getenv("SEED_ADMIN_PASSWORD", "Admin@123")
    customer_email = os.getenv("SEED_CUSTOMER_EMAIL", "jerome@salon.com")
    customer_password = os.getenv("SEED_CUSTOMER_PASSWORD", "Jerome@123")
    # Dev fallback only: prod DDL is owned by Alembic migrations.
    # Canonical metadata covers all 8 tables:
    # users, salons, barbers, services, barber_availability,
    # appointments, queue, appointment_status_history.
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        if db.query(User).filter(User.email == admin_email).first():
            print("Database already seeded. Skipping.")
            return

        salon = Salon(
            name="SmartQueue Demo Salon",
            address="123 Demo Street",
            phone="9999999999",
            # Demo salon hours 09:00-18:00: matches the seeded
            # BarberAvailability window below so the demo appointment
            # (10:00-10:30) sits inside both.
            opening_time=time(9, 0),
            closing_time=time(18, 0),
            status="active",
        )
        db.add(salon)
        db.flush()  # populate salon.salon_id

        admin = User(
            name="Admin",
            email=admin_email,
            password_hash=hash_password(admin_password),
            phone="9999999999",
            role="admin",
        )
        db.add(admin)

        customer = User(
            name="Jerome",
            email=customer_email,
            password_hash=hash_password(customer_password),
            phone="8888888888",
            role="customer",
        )
        db.add(customer)

        barber_user = User(
            name="Arun",
            email=os.getenv("SEED_BARBER_EMAIL", "arun@salon.com"),
            password_hash=hash_password(os.getenv("SEED_BARBER_PASSWORD", "Arun@123")),
            phone="7777777777",
            role="barber",
        )
        db.add(barber_user)

        # Receptionist / front-desk login (canonical `staff` role). Lets devs
        # exercise the staff-only queue endpoints without using the admin user.
        staff_user = User(
            name="Receptionist",
            email=os.getenv("SEED_STAFF_EMAIL", "reception@salon.com"),
            password_hash=hash_password(os.getenv("SEED_STAFF_PASSWORD", "Reception@123")),
            phone="5555555556",
            role="staff",
        )
        db.add(staff_user)
        db.flush()  # populate user_id PKs (User.user_id)

        barbers = [
            Barber(
                name="Arun",
                specialization="Haircut & Styling",
                phone="7777777777",
                availability_status="available",
                user_id=barber_user.user_id,
                salon_id=salon.salon_id,
            ),
            Barber(
                name="Kumar",
                specialization="Beard Trim & Shaving",
                phone="6666666666",
                availability_status="available",
                salon_id=salon.salon_id,
            ),
            Barber(
                name="Ravi",
                specialization="Hair Coloring & Treatment",
                phone="5555555555",
                availability_status="available",
                salon_id=salon.salon_id,
            ),
        ]
        db.add_all(barbers)

        services = [
            Service(service_name="Haircut", description="Professional haircut with styling", duration_minutes=30, price=250.00, status="active", salon_id=salon.salon_id),
            Service(service_name="Hair Styling", description="Premium hair styling and grooming", duration_minutes=45, price=350.00, status="active", salon_id=salon.salon_id),
            Service(service_name="Beard Trim", description="Precision beard trimming and shaping", duration_minutes=20, price=150.00, status="active", salon_id=salon.salon_id),
            Service(service_name="Hair Coloring", description="Professional hair coloring service", duration_minutes=60, price=800.00, status="active", salon_id=salon.salon_id),
            Service(service_name="Facial", description="Deep cleansing facial treatment", duration_minutes=40, price=500.00, status="active", salon_id=salon.salon_id),
        ]
        db.add_all(services)
        db.flush()  # populate barber_id / service_id PKs

        today = date.today()
        db.add(
            BarberAvailability(
                barber_id=barbers[0].barber_id,
                date=today,
                start_time=time(9, 0),
                end_time=time(18, 0),
                status="available",
            )
        )

        appointment = Appointment(
            customer_id=customer.user_id,
            salon_id=salon.salon_id,
            barber_id=barbers[0].barber_id,
            service_id=services[0].service_id,
            appointment_date=today,
            start_time=time(10, 0),
            end_time=time(10, 30),
            status="booked",
            booking_type="online",
        )
        db.add(appointment)
        db.flush()  # populate appointment.appointment_id

        db.add(
            Queue(
                appointment_id=appointment.appointment_id,
                salon_id=salon.salon_id,
                barber_id=barbers[0].barber_id,
                queue_position=1,
                estimated_wait_minutes=0,
                status="waiting",
            )
        )
        db.add(
            AppointmentStatusHistory(
                appointment_id=appointment.appointment_id,
                old_status=None,
                new_status="booked",
            )
        )

        db.commit()
        print("Database seeded successfully!")
        print(f"  Admin: {admin_email}")
        print(f"  Customer: {customer_email}")
        print(f"  Barber: {barber_user.email}")
        print(f"  Receptionist (staff): {staff_user.email}")
        print(f"  Salon: {salon.name} (salon_id={salon.salon_id})")
        print(f"  Barbers: {len(barbers)}, Services: {len(services)}, Demo appointment queue_position=1")
    except Exception as e:
        db.rollback()
        print(f"Error seeding database: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
