"""Tests for the services endpoints."""


def test_list_services_public(client, seeded_data):
    res = client.get("/api/v1/services")
    assert res.status_code == 200
    assert any(s["name"] == "Haircut" for s in res.json())


def test_get_service(client, seeded_data):
    service_id = seeded_data["service"].id
    res = client.get(f"/api/v1/services/{service_id}")
    assert res.status_code == 200
    assert res.json()["price"] == 250.0


def test_get_service_missing(client):
    res = client.get("/api/v1/services/9999")
    assert res.status_code == 404


def test_create_service_requires_admin(client, customer_headers):
    res = client.post(
        "/api/v1/services",
        json={"name": "Shave", "duration": 15, "price": 100},
        headers=customer_headers,
    )
    assert res.status_code == 403


def test_create_service_as_admin(client, admin_headers):
    res = client.post(
        "/api/v1/services",
        json={"name": "Beard Shave", "description": "Fresh shave", "duration": 15, "price": 100},
        headers=admin_headers,
    )
    assert res.status_code == 201
    assert res.json()["name"] == "Beard Shave"


def test_update_service_as_admin(client, admin_headers, seeded_data):
    service_id = seeded_data["service"].id
    res = client.put(f"/api/v1/services/{service_id}", json={"price": 300}, headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["price"] == 300.0


def test_delete_service_as_admin(client, admin_headers, seeded_data):
    service_id = seeded_data["service"].id
    res = client.delete(f"/api/v1/services/{service_id}", headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["success"] is True