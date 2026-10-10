"""Same-slot booking race: concurrent acceptance test (PostgreSQL only).

ACCEPTANCE CRITERION (Task A): 10 threads booking the identical
barber/date/start slot must yield exactly 1 x HTTP 201 + 9 x HTTP 409,
with exactly ONE appointment row for that barber-day in the database
(zero duplicates). Until this test PASSES on a real PostgreSQL, the race
must be reported as NOT resolved.

Skips (never fails) when PostgreSQL is unavailable:
* SMARTQUEUE_PG_TEST_URL env var unset, or
* the URL is unreachable within a short timeout, or
* the psycopg2 driver is not importable in the running interpreter.

The URL must be a full SQLAlchemy URL, e.g.
  SMARTQUEUE_PG_TEST_URL=postgresql+psycopg2://user:pw@localhost:5432/smartqueue_race_test
The database must exist and be dedicated to this test (tables are
created/dropped). Credentials are never printed.
"""

import os
import threading
from datetime import date, time, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

pytestmark = pytest.mark.skipif(
    not os.getenv("SMARTQUEUE_PG_TEST_URL"),
    reason="SMARTQUEUE_PG_TEST_URL not set; needs a real PostgreSQL",
)

try:
    import psycopg2  # noqa: F401
except ImportError:
    psycopg2 = None


def _require_postgres():
    if psycopg2 is None:
        pytest.skip("psycopg2 driver not importable in this interpreter")
    url = os.getenv("SMARTQUEUE_PG_TEST_URL", "")
    try:
        probe = create_engine(url, connect_args={"connect_timeout": 2})
        with probe.connect():
            pass
        probe.dispose()
    except Exception:
        pytest.skip("PostgreSQL at SMARTQUEUE_PG_TEST_URL not reachable")
    return url


@pytest.fixture()
def pg_stack():
    """Isolated Postgres schema + TestClient wired to thread-scoped sessions."""
    import app.models.appointment  # noqa: F401
    import app.models.availability  # noqa: F401
    import app.models.barber  # noqa: F401
    import app.models.queue  # noqa: F401
    import app.models.salon  # noqa: F401
    import app.models.service  # noqa: F401
    import app.models.status_history  # noqa: F401
    import app.models.user  # noqa: F401
    from app.core.database import get_db
    from app.core.security import hash_password
    from app.db.base import Base
    from app.main import app
    from app.models.barber import Barber
    from app.models.salon import Salon
    from app.models.service import Service
    from app.models.user import User

    url = _require_postgres()
    engine = create_engine(url, pool_size=20, max_overflow=10)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    scoped = scoped_session(factory)

    def override_get_db():
        db = scoped()
        try:
            yield db
        finally:
            scoped.remove()

    app.dependency_overrides[get_db] = override_get_db
    try:
        db = scoped()
        slot_date = date.today() + timedelta(days=7)
        salon = Salon(
            name="Race Salon",
            address="9 Race Road",
            phone="9111111111",
            opening_time=time(9, 0),
            closing_time=time(18, 0),
            status="active",
        )
        db.add(salon)
        barber = Barber(
            name="Race Barber",
            specialization="Fade",
            phone="9222222222",
            availability_status="available",
        )
        db.add(barber)
        service = Service(
            service_name="Race Cut",
            description="race test service",
            duration_minutes=30,
            price=200.00,
            status="active",
        )
        db.add(service)
        db.commit()
        db.refresh(salon)
        db.refresh(barber)
        db.refresh(service)
        barber.salon_id = salon.salon_id
        service.salon_id = salon.salon_id
        tokens = []
        for i in range(10):
            user = User(
                name=f"Racer{i}",
                email=f"racer{i}@test.com",
                password_hash=hash_password("racerpass"),
                phone="1234567890",
                role="customer",
            )
            db.add(user)
        db.commit()
        for i in range(10):
            with TestClient(app) as tc:
                res = tc.post(
                    "/api/v1/auth/login",
                    json={"email": f"racer{i}@test.com", "password": "racerpass"},
                )
                assert res.status_code == 200, res.text
                tokens.append(res.json()["data"]["access_token"])
        scoped.remove()
        yield {
            "app": app,
            "engine": engine,
            "scoped": scoped,
            "tokens": tokens,
            "barber_id": barber.barber_id,
            "service_id": service.service_id,
            "slot_date": slot_date.isoformat(),
        }
    finally:
        app.dependency_overrides.clear()
        scoped.remove()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_concurrent_same_slot_yields_single_winner(pg_stack):
    """10 threads, same slot -> exactly 1x201 + 9x409, one row, no dupes."""
    from app.main import app  # noqa: F401
    from app.models.appointment import Appointment

    results = [None] * 10
    barrier = threading.Barrier(10)

    def attempt(idx):
        headers = {"Authorization": f"Bearer {pg_stack['tokens'][idx]}"}
        payload = {
            "barber_id": pg_stack["barber_id"],
            "service_id": pg_stack["service_id"],
            "appointment_date": pg_stack["slot_date"],
            "start_time": "10:00",
        }
        barrier.wait(timeout=30)
        try:
            with TestClient(pg_stack["app"]) as tc:
                res = tc.post(
                    "/api/v1/appointments/", json=payload, headers=headers
                )
                results[idx] = res.status_code
        except Exception as exc:  # record, never hide a thread crash
            results[idx] = f"ERROR:{type(exc).__name__}"

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)

    assert all(isinstance(r, int) for r in results), f"thread errors: {results}"
    assert sorted(results) == [201] + [409] * 9, f"codes: {sorted(results)}"

    session = pg_stack["scoped"]()
    try:
        rows = (
            session.query(Appointment)
            .filter(Appointment.barber_id == pg_stack["barber_id"])
            .all()
        )
        assert len(rows) == 1, f"expected 1 row, found {len(rows)}"
    finally:
        pg_stack["scoped"].remove()
