"""Tests for the barbers endpoints (canonical: barbers.barber_id,
availability_status)."""


def _bid(barber):
    return barber.barber_id


def test_list_barbers_public(client, seeded_data):
    res = client.get("/api/v1/barbers")
    assert res.status_code == 200
    assert any(b["name"] == "Arun" for b in res.json()["data"])


def test_get_barber(client, seeded_data):
    barber_id = _bid(seeded_data["barber"])
    res = client.get(f"/api/v1/barbers/{barber_id}")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body.get("specialization") == "Haircut & Styling"


def test_get_barber_missing(client):
    res = client.get("/api/v1/barbers/9999")
    assert res.status_code == 404


def test_create_barber_requires_admin(client, customer_headers):
    res = client.post(
        "/api/v1/barbers",
        json={"name": "Teja", "specialization": "Shaving"},
        headers=customer_headers,
    )
    assert res.status_code == 403


def test_create_barber_as_admin(client, admin_headers):
    res = client.post(
        "/api/v1/barbers",
        json={
            "name": "Teja",
            "specialization": "Beard & Shaving",
            "phone": "6660001111",
            "availability_status": "available",
            "status": "available",
        },
        headers=admin_headers,
    )
    assert res.status_code == 201
    assert res.json()["data"]["name"] == "Teja"


def test_update_barber_as_admin(client, admin_headers, seeded_data):
    barber_id = _bid(seeded_data["barber"])
    res = client.put(
        f"/api/v1/barbers/{barber_id}",
        json={"availability_status": "busy", "status": "busy"},
        headers=admin_headers,
    )
    assert res.status_code == 200
    body = res.json()["data"]
    assert body.get("availability_status", body.get("status")) == "busy"


def test_delete_barber_as_admin(client, admin_headers, seeded_data):
    barber_id = _bid(seeded_data["barber"])
    res = client.delete(f"/api/v1/barbers/{barber_id}", headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["success"] is True
