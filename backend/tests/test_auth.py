"""Tests for the authentication endpoints (canonical: users.user_id)."""


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
    data = res.json()["data"]
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
    # Canonical dup-email code is 409 Conflict (was 400 before I2-Routes fix).
    assert res.status_code == 409
    assert "already registered" in res.json()["message"].lower()


def test_login_success(client, customer_user):
    res = client.post(
        "/api/v1/auth/login",
        json={"email": "customer@test.com", "password": "customerpass"},
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["access_token"]
    # Canonical PK: users.user_id (no bare `id`).
    user_id = data["user"].get("user_id", data["user"].get("id"))
    assert user_id == customer_user.user_id


def test_login_wrong_password(client, customer_user):
    res = client.post(
        "/api/v1/auth/login",
        json={"email": "customer@test.com", "password": "wrongpass"},
    )
    assert res.status_code == 401


def test_me_requires_valid_token(client):
    res = client.get("/api/v1/auth/me")
    assert res.status_code in (401, 403)  # missing bearer token


def test_me_with_token(client, customer_headers):
    res = client.get("/api/v1/auth/me", headers=customer_headers)
    assert res.status_code == 200
    assert res.json()["data"]["email"] == "customer@test.com"


# ---- Phase 2 extension: cases 3-7 (registration), 10-12 (login), 15-18 (auth) ----
# Envelope contract: every response is {success, data, message}.


def _assert_envelope(body):
    assert set(body.keys()) >= {"success", "data", "message"}
    assert isinstance(body["success"], bool)
    assert isinstance(body["message"], str)


def test_register_invalid_email_rejected(client):
    """Case 3: malformed email -> 422."""
    res = client.post(
        "/api/v1/auth/register",
        json={"name": "Bad Email", "email": "not-an-email", "password": "secret123"},
    )
    assert res.status_code == 422
    body = res.json()
    _assert_envelope(body)
    assert body["success"] is False


def test_register_short_password_rejected(client):
    """Case 4: password shorter than 6 chars -> 422."""
    res = client.post(
        "/api/v1/auth/register",
        json={"name": "Short Pw", "email": "shortpw@test.com", "password": "123"},
    )
    assert res.status_code == 422
    body = res.json()
    _assert_envelope(body)
    assert body["success"] is False


def test_register_defaults_to_customer_role(client):
    """Case 5: no role supplied -> created as customer."""
    res = client.post(
        "/api/v1/auth/register",
        json={"name": "Plain User", "email": "plain@test.com", "password": "secret123"},
    )
    assert res.status_code == 201
    body = res.json()
    _assert_envelope(body)
    assert body["success"] is True
    assert body["data"]["user"]["role"] == "customer"


def test_register_role_admin_blocked(client):
    """Case 6: self-assign role=admin is rejected (extra=forbid) -> 422."""
    res = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Sneaky Admin",
            "email": "sneakyadmin@test.com",
            "password": "secret123",
            "role": "admin",
        },
    )
    assert res.status_code == 422
    assert res.json()["success"] is False


def test_register_role_barber_blocked(client):
    """Case 7: self-assign role=barber is rejected (extra=forbid) -> 422."""
    res = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Sneaky Barber",
            "email": "sneakybarber@test.com",
            "password": "secret123",
            "role": "barber",
        },
    )
    assert res.status_code == 422
    assert res.json()["success"] is False


def test_login_unknown_email_rejected(client):
    """Case 10: unknown email -> 401, error envelope."""
    res = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@test.com", "password": "whatever123"},
    )
    assert res.status_code == 401
    body = res.json()
    _assert_envelope(body)
    assert body["success"] is False
    assert body["data"] is None


def test_login_returns_jwt(client, customer_user):
    """Case 11: successful login returns a decodable JWT whose sub is the user."""
    from app.core.security import decode_access_token

    res = client.post(
        "/api/v1/auth/login",
        json={"email": "customer@test.com", "password": "customerpass"},
    )
    assert res.status_code == 200
    body = res.json()
    _assert_envelope(body)
    token = body["data"]["access_token"]
    assert isinstance(token, str) and len(token) > 20
    assert body["data"].get("token_type", "bearer") == "bearer"
    payload = decode_access_token(token)
    assert payload is not None
    assert str(payload["sub"]) == str(customer_user.user_id)


def test_login_token_has_expiry(client, customer_user):
    """Case 12: JWT carries a future `exp` claim."""
    import time

    res = client.post(
        "/api/v1/auth/login",
        json={"email": "customer@test.com", "password": "customerpass"},
    )
    assert res.status_code == 200
    from app.core.security import decode_access_token

    payload = decode_access_token(res.json()["data"]["access_token"])
    assert payload is not None
    assert "exp" in payload
    assert int(payload["exp"]) > int(time.time())


def test_me_invalid_token_rejected(client):
    """Case 15: garbage signature -> 401."""
    res = client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer garbage.token.here"}
    )
    assert res.status_code == 401
    assert res.json()["success"] is False


def test_me_expired_token_rejected(client, customer_user):
    """Case 16: token created with expires_minutes=-1 -> 401."""
    from app.core.security import create_access_token

    expired = create_access_token(
        data={"sub": str(customer_user.user_id), "role": "customer"},
        expires_minutes=-1,
    )
    res = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"}
    )
    assert res.status_code == 401
    assert res.json()["success"] is False


def test_me_malformed_token_rejected(client):
    """Case 17: malformed token (not a JWT) -> 401."""
    res = client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert res.status_code == 401
    assert res.json()["success"] is False


def test_me_nonexistent_user_rejected(client):
    """Case 18: valid signature but unknown sub -> 401."""
    from app.core.security import create_access_token

    token = create_access_token(data={"sub": "999999", "role": "customer"})
    res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401
    assert res.json()["success"] is False