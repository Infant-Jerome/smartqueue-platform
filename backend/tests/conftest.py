"""Shared pytest fixtures: isolated test database and authenticated test clients.

Canonical Phase 1.1: users.user_id, salons.salon_id, barbers.barber_id,
services.service_id, barber_availability.availability_id,
appointments.appointment_id (customer_id, start_time/end_time),
queue.queue_id (queue_position, estimated_wait_minutes),
appointment_status_history.history_id (->appointments.appointment_id).
Isolated in-memory SQLite only; never touches smartqueue.db.
"""
import os
import sys
import uuid as _notif_uuid
from datetime import date as _date
from datetime import time as _time
from datetime import timedelta as _timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import get_db  # noqa: E402
from app.db.base import Base  # noqa: E402  (single canonical Base)
# Register every canonical table before create_all.
import app.models.appointment  # noqa: E402,F401
import app.models.availability  # noqa: E402,F401
import app.models.barber  # noqa: E402,F401
import app.models.queue  # noqa: E402,F401
import app.models.salon  # noqa: E402,F401
import app.models.service  # noqa: E402,F401
import app.models.status_history  # noqa: E402,F401
import app.models.user  # noqa: E402,F401
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models.availability import BarberAvailability  # noqa: E402
from app.models.barber import Barber  # noqa: E402
from app.models.salon import Salon  # noqa: E402
from app.models.service import Service  # noqa: E402
from app.models.user import User  # noqa: E402

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
def barber_user(db_session):
    return make_user(db_session, "Barber", "barber@test.com", "barberpass", role="barber")


@pytest.fixture()
def receptionist_user(db_session):
    return make_user(db_session, "Receptionist", "receptionist@test.com", "receptionistpass", role="receptionist")


@pytest.fixture()
def seeded_data(db_session):
    barber = Barber(
        name="Arun",
        specialization="Haircut & Styling",
        phone="7777777777",
        availability_status="available",
    )
    db_session.add(barber)
    service = Service(
        service_name="Haircut",
        description="Professional haircut with styling",
        duration_minutes=30,
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


@pytest.fixture()
def barber_headers(client, barber_user):
    return auth_headers(client, barber_user.email, "barberpass")


# ---------------------------------------------------------------------------
# Phase 3 (B4-Tests): salon / barber / service / availability fixtures.
# Isolated in-memory SQLite only. `slot_availability` covers 09:00-18:00 on
# `slot_date` for `salon_barber` so positive booking tests run inside a
# valid window; negative tests use dates/barbers with NO coverage.
# ---------------------------------------------------------------------------

@pytest.fixture()
def slot_date():
    return _date.today() + _timedelta(days=7)


@pytest.fixture()
def salon(db_session):
    row = Salon(
        name="Phase3 Salon",
        address="1 Test Street",
        phone="9000000001",
        opening_time=_time(9, 0),
        closing_time=_time(18, 0),
        status="active",
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


@pytest.fixture()
def salon2(db_session):
    row = Salon(
        name="Phase3 Salon Two",
        address="2 Test Street",
        phone="9000000009",
        opening_time=_time(9, 0),
        closing_time=_time(18, 0),
        status="active",
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


@pytest.fixture()
def inactive_salon(db_session):
    row = Salon(
        name="Closed Salon",
        address="3 Test Street",
        phone="9000000008",
        opening_time=_time(9, 0),
        closing_time=_time(18, 0),
        status="inactive",
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


@pytest.fixture()
def salon_barber(db_session, salon):
    row = Barber(
        name="Phase3 Barber",
        specialization="Fade",
        phone="9000000002",
        availability_status="available",
        salon_id=salon.salon_id,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


@pytest.fixture()
def second_barber(db_session, salon):
    """Same salon but with NO availability rows (barber-not-available case)."""
    row = Barber(
        name="Phase3 Barber Two",
        specialization="Beard",
        phone="9000000003",
        availability_status="available",
        salon_id=salon.salon_id,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


@pytest.fixture()
def salon2_barber(db_session, salon2):
    row = Barber(
        name="Other Salon Barber",
        specialization="Color",
        phone="9000000004",
        availability_status="available",
        salon_id=salon2.salon_id,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


@pytest.fixture()
def salon_service(db_session, salon):
    row = Service(
        service_name="Phase3 Cut",
        description="Phase3 test haircut",
        duration_minutes=30,
        price=300.00,
        status="active",
        salon_id=salon.salon_id,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


@pytest.fixture()
def second_service(db_session, salon):
    row = Service(
        service_name="Phase3 Shave",
        description="Phase3 test shave",
        duration_minutes=30,
        price=150.00,
        status="active",
        salon_id=salon.salon_id,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


@pytest.fixture()
def salon2_service(db_session, salon2):
    row = Service(
        service_name="Other Salon Cut",
        description="Other salon service",
        duration_minutes=30,
        price=300.00,
        status="active",
        salon_id=salon2.salon_id,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


@pytest.fixture()
def inactive_service(db_session, salon):
    row = Service(
        service_name="Retired Cut",
        description="Inactive service",
        duration_minutes=30,
        price=100.00,
        status="inactive",
        salon_id=salon.salon_id,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


@pytest.fixture()
def slot_availability(db_session, salon_barber, slot_date):
    """Availability covering the whole booking slot (09:00-18:00)."""
    row = BarberAvailability(
        barber_id=salon_barber.barber_id,
        date=slot_date,
        start_time=_time(9, 0),
        end_time=_time(18, 0),
        status="available",
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


@pytest.fixture()
def barber_profile(db_session, barber_user, salon):
    """Barber row owned by the `barber` login (own-read / modify tests)."""
    row = Barber(
        name="Login Barber",
        specialization="Fade",
        phone="9000000005",
        availability_status="available",
        salon_id=salon.salon_id,
        user_id=barber_user.user_id,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


@pytest.fixture()
def other_barber_profile(db_session, salon):
    """Barber row NOT owned by the `barber` login."""
    row = Barber(
        name="Stranger Barber",
        specialization="Trim",
        phone="9000000006",
        availability_status="available",
        salon_id=salon.salon_id,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


@pytest.fixture()
def customer2_user(db_session):
    return make_user(db_session, "Customer2", "customer2@test.com", "customer2pass", role="customer")


@pytest.fixture()
def customer2_headers(client, customer2_user):
    return auth_headers(client, customer2_user.email, "customer2pass")


@pytest.fixture()
def receptionist_headers(client, receptionist_user):
    return auth_headers(client, receptionist_user.email, "receptionistpass")


# ---------------------------------------------------------------------------
# Phase 5A (WS3-Tests): WebSocket queue fixtures/helpers ONLY.
# Isolated in-memory SQLite; TestClient.websocket_connect with ?token= JWT.
# Server-push model: mutations happen via REST, WS only asserts broadcasts.
# ---------------------------------------------------------------------------

WS_PATH_CANDIDATES = (
    "/api/v1/queue/ws",
    "/api/v1/queue/live",
    "/api/v1/ws/queue",
    "/ws/queue",
)


def ws_raw_token_from_headers(headers):
    """Extract the raw JWT from an Authorization header dict."""
    return headers["Authorization"].split(" ", 1)[1]


def ws_login_token(client, email, password):
    """Log in via REST and return the raw JWT string for ?token= use."""
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["data"]["access_token"]


def ws_url(base_path, token=None, salon_id=None, barber_id=None):
    """Build a WS URL with ?token= JWT plus optional scope params."""
    from urllib.parse import urlencode

    params = {}
    if token is not None:
        params["token"] = token
    if salon_id is not None:
        params["salon_id"] = salon_id
    if barber_id is not None:
        params["barber_id"] = barber_id
    qs = urlencode(params)
    return f"{base_path}?{qs}" if qs else base_path


def ws_make_expired_token(user_id):
    """Signed-but-expired JWT for auth test 4."""
    from app.core.security import create_access_token

    return create_access_token({"sub": str(user_id)}, expires_minutes=-1)


def ws_make_unknown_user_token():
    """Validly-signed JWT for a user id that does not exist (auth test 5)."""
    from app.core.security import create_access_token

    return create_access_token({"sub": "999999999"}, expires_minutes=30)


def ws_make_invalid_token():
    """Tampered/garbage token for auth test 3 (never a valid signature)."""
    return "invalid.token.signature"


# Real Phase 5A route (WS1-Infra): WS /api/v1/ws/queue/{salon_id}
# with ?token=<JWT>&barber_id=<int>&date=<YYYY-MM-DD>.
WS_QUEUE_PATH_TEMPLATE = "/api/v1/ws/queue/{salon_id}"


def ws_queue_url(salon_id, token=None, barber_id=None, date_str=None):
    """Build the real queue-WS URL: path-param salon + query token/scope."""
    from urllib.parse import urlencode

    params = {}
    if token is not None:
        params["token"] = token
    if barber_id is not None:
        params["barber_id"] = barber_id
    if date_str is not None:
        params["date"] = date_str
    qs = urlencode(params)
    base = WS_QUEUE_PATH_TEMPLATE.format(salon_id=salon_id)
    return f"{base}?{qs}" if qs else base


@pytest.fixture()
def customer_token(client, customer_user):
    return ws_login_token(client, customer_user.email, "customerpass")


@pytest.fixture()
def admin_token(client, admin_user):
    return ws_login_token(client, admin_user.email, "adminpass")


@pytest.fixture()
def staff_token(client, receptionist_user):
    return ws_login_token(client, receptionist_user.email, "receptionistpass")


@pytest.fixture()
def barber_token(client, barber_user):
    return ws_login_token(client, barber_user.email, "barberpass")


# ---------------------------------------------------------------------------
# Phase 5B (N3-Tests): notification fixtures / helpers ONLY.
# Isolated in-memory SQLite; no app code touched. `queue_events` outbox is
# the observable side-effect for trigger tests until a real notifications
# module lands. Local fakes for providers/prefs/dedupe live in
# test_notifications.py; these fixtures only manage shared state.
# ---------------------------------------------------------------------------


@pytest.fixture()
def notif_outbox():
    """Clear the queue_events outbox before/after; yield the module."""
    from app.services import queue_events as _qe

    _qe.clear_outbox()
    yield _qe
    _qe.clear_outbox()


@pytest.fixture()
def notif_outbox_size(notif_outbox):
    """Return current outbox length (after clearing via notif_outbox)."""
    return len(notif_outbox.peek_outbox())


@pytest.fixture()
def notif_prefs():
    """Default notification channel prefs (all enabled). Tests mutate a copy."""
    return {"email": True, "sms": True, "push": True}


@pytest.fixture()
def notif_dedupe_store():
    """Empty idempotency store (event_key -> result). In-memory only."""
    return {}


@pytest.fixture()
def notif_event_factory():
    """Factory for fake notification events with unique idempotency keys."""
    def _make(event_type="booked", channel="email", user_id=1, key=None, **extra):
        payload = {
            "event_id": key or f"evt-{_notif_uuid.uuid4().hex[:12]}",
            "event_type": event_type,
            "channel": channel,
            "user_id": user_id,
        }
        payload.update(extra)
        return payload
    return _make


@pytest.fixture()
def notif_service():
    """Isolated notification-service state (OUTBOX/_SEEN_KEYS/mocks/prefs).

    Clears process-global notification state before/after. Never touches
    app code; tests only.
    """
    from app.notifications import preferences as _prefs
    from app.notifications import providers as _providers
    from app.notifications import service as _svc

    _svc.OUTBOX.clear()
    try:
        _svc._SEEN_KEYS.clear()
    except Exception:
        pass
    _providers.clear_mock_sends()
    _prefs.clear_preferences()
    yield _svc
    _svc.OUTBOX.clear()
    try:
        _svc._SEEN_KEYS.clear()
    except Exception:
        pass
    _providers.clear_mock_sends()
    _prefs.clear_preferences()


@pytest.fixture()
def notif_test_session(db_session, monkeypatch):
    """Point the notification service at the isolated test DB (never prod).

    The service resolves recipients/persists via ``app.db.database``
    ``SessionLocal`` (production DB). This patches that symbol to serve
    fresh sessions bound to the test engine, so trigger tests stay
    isolated in-memory SQLite. Test-only; no app code touched.
    """
    import app.db.database as _dbmod
    from sqlalchemy.orm import sessionmaker as _sm

    factory = _sm(autocommit=False, autoflush=False, bind=db_session.bind)
    monkeypatch.setattr(_dbmod, "SessionLocal", factory)
    return db_session


# ---------------------------------------------------------------------------
# Phase 5C (S3-Tests): SAWTE seeding fixtures/helpers ONLY.
# Isolated in-memory SQLite; no app code touched.
#
# Seeding approach (documented): direct DB rows carrying
# ``actual_duration_minutes`` plus backdated
# ``appointment_status_history.changed_at`` stamps. This complements the
# S2 write path (complete -> measured actual in-transaction; sub-minute
# test services record 1): direct rows seed unit-level history on past
# dates (overlap/availability checks bypassed by design -- they only run
# on the REST booking path), while REST serve/complete seeds integration
# history. Per S2 (services/sawte.py decision 3) "latest" keys on
# ``appointment_id DESC``; ``changed_at`` backdating keeps
# ``serving_remaining`` elapsed math deterministic.
# ---------------------------------------------------------------------------

_SAWTE_EXTRA_N = {"n": 0}


@pytest.fixture()
def sawte_extra_customer_factory(client, db_session):
    """Factory creating extra isolated customers -> (user, headers)."""
    from app.core.security import hash_password as _hash
    from app.models.user import User as _User

    def _make(name="SawteExtra"):
        _SAWTE_EXTRA_N["n"] += 1
        n = _SAWTE_EXTRA_N["n"]
        email = f"sawte-extra-{n}@test.com"
        user = _User(
            name=f"{name}{n}",
            email=email,
            password_hash=_hash("sawtepass"),
            phone="1234567890",
            role="customer",
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        res = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "sawtepass"},
        )
        assert res.status_code == 200, res.text
        headers = {"Authorization": "Bearer " + res.json()["data"]["access_token"]}
        return user, headers

    return _make


@pytest.fixture()
def sawte_seed_history(db_session):
    """Factory seeding completed history with measured actuals.

    Direct ``Appointment`` rows (default status completed, actual set)
    + one backdated history row each (in_progress -> completed).
    ``statuses`` may be a single status or a per-row list (exclusion
    tests). ``durations`` entries may be None (NULL-actual test).
    Returns the created Appointment rows (insertion order = oldest first,
    so the LAST row is "latest" per appointment_id DESC).
    """
    from datetime import datetime as _dt
    from datetime import time as _tm
    from datetime import timedelta as _td

    from app.models.appointment import Appointment as _Appointment
    from app.models.status_history import AppointmentStatusHistory as _History

    def _seed(*, barber_id, service_id, customer_id, durations,
              salon_id=None, days_ago_start=30, statuses="completed"):
        if isinstance(statuses, str):
            statuses = [statuses] * len(durations)
        assert len(statuses) == len(durations), "statuses/durations length mismatch"
        base = _dt.utcnow() - _td(days=days_ago_start)
        rows = []
        for i, (dur, st) in enumerate(zip(durations, statuses)):
            stamp = base - _td(days=i)
            appt = _Appointment(
                customer_id=customer_id,
                salon_id=salon_id,
                barber_id=barber_id,
                service_id=service_id,
                appointment_date=stamp.date(),
                start_time=_tm(10, 0),
                end_time=_tm(10, 30),
                status=st,
                booking_type="online",
                actual_duration_minutes=dur,
            )
            db_session.add(appt)
            db_session.flush()
            db_session.add(_History(
                appointment_id=appt.appointment_id,
                old_status="in_progress",
                new_status=st,
                changed_at=stamp,
            ))
            rows.append(appt)
        db_session.commit()
        for appt in rows:
            db_session.refresh(appt)
        return rows

    return _seed