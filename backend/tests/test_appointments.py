"""Tests for the appointments endpoints."""
from datetime import date, timedelta


def future_date(days=1):
    return (date.today() + timedelta(days=days)).isoformat()


def past_date():
    return (date.today() - timedelta(days=1)).isoformat()


def booking_payload(seeded_data, date_str=None, time_str="10:00"):
    return {
        "barber_id": seeded_data["barber"].id,
        "service_id": seeded_data["service"].id,
        "appointment_date": date_str or future_date(),
        "appointment_time": time_str,
    }


def test_create_appointment(client, customer_headers, seeded_data):
    res = client.post("/api/v1/appointments", json=booking_payload(seeded_data), headers=customer_headers)
    assert res.status_code == 201
    data = res.json()["data"]
    assert data["status"] == "booked"
    assert data["queue_number"] == 1


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
    from app.models.models import Barber

    other_barber = Barber(name="Kumar", specialization="Shaving", status="available")
    db_session.add(other_barber)
    db_session.commit()
    db_session.refresh(other_barber)

    first = booking_payload(seeded_data)
    assert client.post("/api/v1/appointments", json=first, headers=customer_headers).status_code == 201

    second = booking_payload(seeded_data, time_str="10:00")
    second["barber_id"] = other_barber.id
    res = client.post("/api/v1/appointments", json=second, headers=customer_headers)
    assert res.status_code == 409
    assert "already have an appointment" in res.json()["message"].lower()


def test_customer_can_only_cancel_own_appointment(client, customer_headers, seeded_data):
    res = client.post("/api/v1/appointments", json=booking_payload(seeded_data), headers=customer_headers)
    appointment_id = res.json()["data"]["id"]

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
    from app.models.models import User

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
    booked_for_customer = [a["id"] for a in res.json()["data"]]
    assert len(booked_for_customer) == 1