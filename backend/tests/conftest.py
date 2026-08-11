"""Shared pytest fixtures: isolated test database and authenticated test clients."""
import os
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import Base, get_db  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models.models import Barber, Service, User  # noqa: E402

TestSessionLocal = sessionmaker(autocommit=False, autoflush=False)


@pytest.fixture()
def db_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def db_session(db_engine):
    TestSessionLocal.configure(bind=db_engine)
    session = TestSessionLocal()
    yield session
    session.close()


@pytest.fixture()
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def make_user(db, name, email, password, role="customer"):
    user = User(
        name=name,
        email=email,
        password_hash=hash_password(password),
        phone="1234567890",
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def admin_user(db_session):
    return make_user(db_session, "Admin", "admin@test.com", "adminpass", role="admin")


@pytest.fixture()
def customer_user(db_session):
    return make_user(db_session, "Customer", "customer@test.com", "customerpass", role="customer")


@pytest.fixture()
def seeded_data(db_session):
    barber = Barber(
        name="Arun",
        specialization="Haircut & Styling",
        phone="7777777777",
        status="available",
    )
    db_session.add(barber)
    service = Service(
        name="Haircut",
        description="Professional haircut with styling",
        duration=30,
        price=250.00,
        status="active",
    )
    db_session.add(service)
    db_session.commit()
    db_session.refresh(barber)
    db_session.refresh(service)
    return {"barber": barber, "service": service}


def auth_headers(client, email, password):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


@pytest.fixture()
def admin_headers(client, admin_user):
    return auth_headers(client, admin_user.email, "adminpass")


@pytest.fixture()
def customer_headers(client, customer_user):
    return auth_headers(client, customer_user.email, "customerpass")