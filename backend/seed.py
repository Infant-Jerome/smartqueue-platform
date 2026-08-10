"""Seed the database with sample data."""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.core.database import SessionLocal, engine, Base
from app.core.security import hash_password
from app.models.models import User, Barber, Service


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        if db.query(User).filter(User.email == "admin@salon.com").first():
            print("Database already seeded. Skipping.")
            return

        admin = User(
            name="Admin",
            email="admin@salon.com",
            password_hash=hash_password("Admin@123"),
            phone="9999999999",
            role="admin",
        )
        db.add(admin)

        customer = User(
            name="Jerome",
            email="jerome@salon.com",
            password_hash=hash_password("Jerome@123"),
            phone="8888888888",
            role="customer",
        )
        db.add(customer)

        barbers = [
            Barber(name="Arun", specialization="Haircut & Styling", phone="7777777777", status="available"),
            Barber(name="Kumar", specialization="Beard Trim & Shaving", phone="6666666666", status="available"),
            Barber(name="Ravi", specialization="Hair Coloring & Treatment", phone="5555555555", status="available"),
        ]
        db.add_all(barbers)

        services = [
            Service(name="Haircut", description="Professional haircut with styling", duration=30, price=250.00, status="active"),
            Service(name="Hair Styling", description="Premium hair styling and grooming", duration=45, price=350.00, status="active"),
            Service(name="Beard Trim", description="Precision beard trimming and shaping", duration=20, price=150.00, status="active"),
            Service(name="Hair Coloring", description="Professional hair coloring service", duration=60, price=800.00, status="active"),
            Service(name="Facial", description="Deep cleansing facial treatment", duration=40, price=500.00, status="active"),
        ]
        db.add_all(services)

        db.commit()
        print("Database seeded successfully!")
        print("  Admin: admin@salon.com / Admin@123")
        print("  Customer: jerome@salon.com / Jerome@123")
    except Exception as e:
        db.rollback()
        print(f"Error seeding database: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
