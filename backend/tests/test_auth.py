"""Tests for the authentication endpoints."""


def test_register_creates_customer(client):
    res = client.post(
        "/api/v1/auth/register",
        json={
            "name": "New User",
            "email": "new@test.com",
            "password": "secret123",
            "phone": "5551234567",
        },
    )
    assert res.status_code == 201
    data = res.json()
    assert data["access_token"]
    assert data["user"]["email"] == "new@test.com"
    assert data["user"]["role"] == "customer"


def test_register_duplicate_email_rejected(client):
    payload = {
        "name": "New User",
        "email": "dup@test.com",
        "password": "secret123",
    }
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201
    res = client.post("/api/v1/auth/register", json=payload)
    assert res.status_code == 400
    assert "already registered" in res.json()["detail"].lower()


def test_login_success(client, customer_user):
    res = client.post(
        "/api/v1/auth/login",
        json={"email": "customer@test.com", "password": "customerpass"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["access_token"]
    assert data["user"]["id"] == customer_user.id


def test_login_wrong_password(client, customer_user):
    res = client.post(
        "/api/v1/auth/login",
        json={"email": "customer@test.com", "password": "wrongpass"},
    )
    assert res.status_code == 401


def test_me_requires_valid_token(client):
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 403  # HTTPBearer auto-error


def test_me_with_token(client, customer_headers):
    res = client.get("/api/v1/auth/me", headers=customer_headers)
    assert res.status_code == 200
    assert res.json()["email"] == "customer@test.com"