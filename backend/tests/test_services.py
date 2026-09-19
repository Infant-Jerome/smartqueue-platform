"""Tests for the services endpoints (canonical: services.service_id,
service_name, duration_minutes)."""


def _sid(service):
    return service.service_id


def _name(svc_json):
    return svc_json.get("service_name", svc_json.get("name"))


def _duration(svc_json):
    return svc_json.get("duration_minutes", svc_json.get("duration"))


def test_list_services_public(client, seeded_data):
    res = client.get("/api/v1/services")
    assert res.status_code == 200
    assert any(_name(s) == "Haircut" for s in res.json()["data"])


def test_get_service(client, seeded_data):
    service_id = _sid(seeded_data["service"])
    res = client.get(f"/api/v1/services/{service_id}")
    assert res.status_code == 200
    assert res.json()["data"]["price"] == 250.0


def test_get_service_missing(client):
    res = client.get("/api/v1/services/9999")
    assert res.status_code == 404


def test_create_service_requires_admin(client, customer_headers):
    res = client.post(
        "/api/v1/services",
        json={"service_name": "Shave", "name": "Shave", "duration_minutes": 15, "duration": 15, "price": 100},
        headers=customer_headers,
    )
    assert res.status_code == 403


def test_create_service_as_admin(client, admin_headers):
    res = client.post(
        "/api/v1/services",
        json={
            "service_name": "Beard Shave",
            "name": "Beard Shave",
            "description": "Fresh shave",
            "duration_minutes": 15,
            "duration": 15,
            "price": 100,
        },
        headers=admin_headers,
    )
    assert res.status_code == 201
    assert _name(res.json()["data"]) == "Beard Shave"


def test_update_service_as_admin(client, admin_headers, seeded_data):
    service_id = _sid(seeded_data["service"])
    res = client.put(f"/api/v1/services/{service_id}", json={"price": 300}, headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["data"]["price"] == 300.0


def test_delete_service_as_admin(client, admin_headers, seeded_data):
    service_id = _sid(seeded_data["service"])
    res = client.delete(f"/api/v1/services/{service_id}", headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["success"] is True
