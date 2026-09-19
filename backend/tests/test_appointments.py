"""Tests for the appointments endpoints.

Canonical Phase 1.1: appointments.appointment_id (customer_id,
start_time/end_time). Payloads carry canonical start_time/end_time plus the
legacy appointment_time alias so the suite passes both before and after the
API migration lands; response assertions accept either key.
"""
from datetime import date, timedelta


def future_date(days=1):
    return (date.today() + timedelta(days=days)).isoformat()


def past_date():
    return (date.today() - timedelta(days=1)).isoformat()


def booking_payload(seeded_data, date_str=None, time_str="10:00"):
    start = time_str
    end_h, end_m = int(start[:2]) + 0, int(start[3:5]) + 30
    if end_m >= 60:
        end_h += 1
        end_m -= 60
    end = f"{end_h:02d}:{end_m:02d}"
    return {
        "barber_id": seeded_data["barber"].barber_id,
        "service_id": seeded_data["service"].service_id,
        "appointment_date": date_str or future_date(),
        # Canonical:
        "start_time": start,
        "end_time": end,
        # Legacy alias (API transition):
        "appointment_time": start,
    }


def _aid(data):
    return data.get("appointment_id", data.get("id"))


def _qnum(data):
    return data.get("queue_position", data.get("queue_number"))


def test_create_appointment(client, customer_headers, seeded_data):
    res = client.post("/api/v1/appointments", json=booking_payload(seeded_data), headers=customer_headers)
    assert res.status_code == 201, res.text
    data = res.json()["data"]
    assert data["status"] == "booked"
    assert _qnum(data) == 1
    assert _aid(data) is not None


def test_create_appointment_in_past_rejected(client, customer_headers, seeded_data):
    res = client.post(
        "/api/v1/appointments",
        json=booking_payload(seeded_data, date_str=past_date()),
        headers=customer_headers,
    )
    assert res.status_code == 400
    assert "past" in res.json()["message"].lower()


def test_double_booking_conflict(client, customer_headers, seeded_data):
    payload = booking_payload(seeded_data)
    assert client.post("/api/v1/appointments", json=payload, headers=customer_headers).status_code == 201
    res = client.post("/api/v1/appointments", json=payload, headers=customer_headers)
    assert res.status_code == 409


def test_same_customer_same_time_conflict(client, customer_headers, db_session, seeded_data):
    from app.models.barber import Barber

    other_barber = Barber(name="Kumar", specialization="Shaving", availability_status="available")
    db_session.add(other_barber)
    db_session.commit()
    db_session.refresh(other_barber)

    first = booking_payload(seeded_data)
    assert client.post("/api/v1/appointments", json=first, headers=customer_headers).status_code == 201

    second = booking_payload(seeded_data, time_str="10:00")
    second["barber_id"] = other_barber.barber_id
    res = client.post("/api/v1/appointments", json=second, headers=customer_headers)
    assert res.status_code == 409
    assert "already have an appointment" in res.json()["message"].lower()


def test_customer_can_only_cancel_own_appointment(client, customer_headers, seeded_data):
    res = client.post("/api/v1/appointments", json=booking_payload(seeded_data), headers=customer_headers)
    assert res.status_code == 201, res.text
    appointment_id = _aid(res.json()["data"])

    res = client.put(
        f"/api/v1/appointments/{appointment_id}",
        json={"status": "completed"},
        headers=customer_headers,
    )
    assert res.status_code == 403

    res = client.put(
        f"/api/v1/appointments/{appointment_id}",
        json={"status": "cancelled"},
        headers=customer_headers,
    )
    assert res.status_code == 200
    assert res.json()["data"]["status"] == "cancelled"


def test_list_appointments_scoped_to_customer(
    client, customer_user, customer_headers, db_session, seeded_data
):
    from app.core.security import hash_password
    from app.models.user import User

    other = User(
        name="Other",
        email="other@test.com",
        password_hash=hash_password("otherpass"),
        phone="0000000000",
        role="customer",
    )
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)

    def book_as(user, password):
        token_res = client.post(
            "/api/v1/auth/login", json={"email": user.email, "password": password}
        )
        headers = {"Authorization": f"Bearer {token_res.json()['data']['access_token']}"}
        return client.post(
            "/api/v1/appointments",
            json=booking_payload(seeded_data, time_str="10:00" if user is customer_user else "11:00"),
            headers=headers,
        )

    assert book_as(customer_user, "customerpass").status_code == 201
    assert book_as(other, "otherpass").status_code == 201

    res = client.get("/api/v1/appointments", headers=customer_headers)
    assert res.status_code == 200
    booked_for_customer = [_aid(a) for a in res.json()["data"]]
    assert len(booked_for_customer) == 1
