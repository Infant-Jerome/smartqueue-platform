"""Tests for the barbers endpoints."""


def test_list_barbers_public(client, seeded_data):
    res = client.get("/api/v1/barbers")
    assert res.status_code == 200
    assert any(b["name"] == "Arun" for b in res.json())


def test_get_barber(client, seeded_data):
    barber_id = seeded_data["barber"].id
    res = client.get(f"/api/v1/barbers/{barber_id}")
    assert res.status_code == 200
    assert res.json()["specialization"] == "Haircut & Styling"


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
        json={"name": "Teja", "specialization": "Beard & Shaving", "phone": "6660001111"},
        headers=admin_headers,
    )
    assert res.status_code == 201
    assert res.json()["name"] == "Teja"


def test_update_barber_as_admin(client, admin_headers, seeded_data):
    barber_id = seeded_data["barber"].id
    res = client.put(
        f"/api/v1/barbers/{barber_id}", json={"status": "busy"}, headers=admin_headers
    )
    assert res.status_code == 200
    assert res.json()["status"] == "busy"


def test_delete_barber_as_admin(client, admin_headers, seeded_data):
    barber_id = seeded_data["barber"].id
    res = client.delete(f"/api/v1/barbers/{barber_id}", headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["success"] is True