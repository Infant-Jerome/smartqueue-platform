"""Tests for the queue endpoints."""
from datetime import date, timedelta


def future_date(days=1):
    return (date.today() + timedelta(days=days)).isoformat()


def book_appointment(client, customer_headers, seeded_data, time_str="10:00"):
    res = client.post(
        "/api/v1/appointments",
        json={
            "barber_id": seeded_data["barber"].id,
            "service_id": seeded_data["service"].id,
            "appointment_date": future_date(),
            "appointment_time": time_str,
        },
        headers=customer_headers,
    )
    assert res.status_code == 201, res.text
    return res.json()


def test_queue_requires_staff(client, customer_headers):
    res = client.get("/api/v1/queue", headers=customer_headers)
    assert res.status_code == 403


def test_my_position_no_queue(client, customer_headers):
    res = client.get("/api/v1/queue/my-position", headers=customer_headers)
    assert res.status_code == 200
    assert res.json()["has_queue"] is False


def test_my_position_with_active_appointment(client, customer_headers, seeded_data):
    appt = book_appointment(client, customer_headers, seeded_data)
    res = client.get("/api/v1/queue/my-position", headers=customer_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["has_queue"] is True
    assert data["queue_number"] == appt["queue_number"]
    assert data["people_ahead"] == 0


def test_queue_list_and_serve_lifecycle(client, customer_headers, admin_headers, seeded_data):
    appt = book_appointment(client, customer_headers, seeded_data)

    entries = client.get("/api/v1/queue", headers=admin_headers).json()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["status"] == "waiting"

    updated = client.put(f"/api/v1/queue/{entry['id']}", json={"status": "serving"}, headers=admin_headers)
    assert updated.status_code == 200
    assert updated.json()["status"] == "serving"

    served = client.post(f"/api/v1/queue/{entry['id']}/serve", headers=admin_headers)
    assert served.status_code == 400  # already serving

    completed = client.post(f"/api/v1/queue/{entry['id']}/complete", headers=admin_headers)
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"

    queue_after = client.get("/api/v1/queue", headers=admin_headers).json()
    assert len(queue_after) == 0  # completed entries filtered out