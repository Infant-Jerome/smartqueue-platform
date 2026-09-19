"""RBAC + profile + security tests (Phase 2, cases 19-32).

Isolated in-memory SQLite via conftest `client` (get_db override); never
touches prod smartqueue.db. All responses must follow the envelope
{success, data, message}.
"""

import json


SERVICE_PAYLOAD = {
    "service_name": "RBAC Cut",
    "duration_minutes": 30,
    "price": 250.0,
}


def _assert_envelope(body):
    assert set(body.keys()) >= {"success", "data", "message"}
    assert isinstance(body["success"], bool)
    assert isinstance(body["message"], str)


# ---------- RBAC 19-25 ----------


def test_customer_cannot_create_service(client, customer_headers):
    """Case 19: customer -> admin-only POST /services -> 403."""
    res = client.post("/api/v1/services", json=SERVICE_PAYLOAD, headers=customer_headers)
    assert res.status_code == 403
    body = res.json()
    _assert_envelope(body)
    assert body["success"] is False


def test_barber_cannot_create_service(client, barber_headers):
    """Case 20: barber -> admin-only POST /services -> 403."""
    res = client.post("/api/v1/services", json=SERVICE_PAYLOAD, headers=barber_headers)
    assert res.status_code == 403
    assert res.json()["success"] is False


def test_receptionist_cannot_create_service(client, receptionist_headers):
    """Case 21: receptionist (front-desk, non-admin) -> admin-only -> 403."""
    res = client.post(
        "/api/v1/services", json=SERVICE_PAYLOAD, headers=receptionist_headers
    )
    assert res.status_code == 403
    assert res.json()["success"] is False


def test_admin_can_read_other_user(client, admin_headers, customer_user):
    """Case 22: admin is allowed on protected user read -> 200 + envelope."""
    res = client.get(
        f"/api/v1/users/{customer_user.user_id}", headers=admin_headers
    )
    assert res.status_code == 200
    body = res.json()
    _assert_envelope(body)
    assert body["success"] is True
    assert body["data"]["email"] == customer_user.email


def test_customer_cannot_modify_role(client, customer_headers, customer_user):
    """Case 23: customer cannot change (own) role -> 403."""
    role_res = client.patch(
        f"/api/v1/users/{customer_user.user_id}/role",
        json={"role": "admin"},
        headers=customer_headers,
    )
    assert role_res.status_code == 403
    body = role_res.json()
    _assert_envelope(body)
    assert body["success"] is False


def test_non_admin_cannot_change_other_role(client, barber_headers, customer_user):
    """Case 24: barber cannot change another user's role -> 403."""
    res = client.patch(
        f"/api/v1/users/{customer_user.user_id}/role",
        json={"role": "admin"},
        headers=barber_headers,
    )
    assert res.status_code == 403
    body = res.json()
    _assert_envelope(body)
    assert body["success"] is False


def test_admin_can_change_role(client, admin_headers, customer_user):
    """Case 25: admin can change a user's role -> 200, role persisted."""
    res = client.patch(
        f"/api/v1/users/{customer_user.user_id}/role",
        json={"role": "barber"},
        headers=admin_headers,
    )
    assert res.status_code == 200
    body = res.json()
    _assert_envelope(body)
    assert body["success"] is True
    assert body["data"]["role"] == "barber"


# ---------- Profile 26-28 ----------


def test_get_own_profile(client, customer_headers, customer_user):
    """Case 26: user can read own profile -> 200, no secret fields."""
    res = client.get(
        f"/api/v1/users/{customer_user.user_id}", headers=customer_headers
    )
    assert res.status_code == 200
    body = res.json()
    _assert_envelope(body)
    assert body["data"]["email"] == "customer@test.com"
    assert "password_hash" not in body["data"]


def test_cannot_read_other_profile(client, customer_headers, admin_user):
    """Case 27: non-admin cannot perform protected op on another user -> 403."""
    res = client.get(
        f"/api/v1/users/{admin_user.user_id}", headers=customer_headers
    )
    assert res.status_code == 403
    assert res.json()["success"] is False


def test_no_password_hash_in_user_responses(client, customer_headers, customer_user):
    """Case 28: register/login/me/get-user never expose password_hash."""
    reg = client.post(
        "/api/v1/auth/register",
        json={"name": "Hash Check", "email": "hashcheck@test.com", "password": "secret123"},
    )
    assert reg.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "customer@test.com", "password": "customerpass"},
    )
    me = client.get("/api/v1/auth/me", headers=customer_headers)
    get_user = client.get(
        f"/api/v1/users/{customer_user.user_id}", headers=customer_headers
    )
    for res in (reg, login, me, get_user):
        assert res.status_code in (200, 201)
        dumped = json.dumps(res.json())
        assert "password_hash" not in dumped


# ---------- Security 29-32 ----------


def test_password_stored_as_bcrypt_hash(db_session, customer_user):
    """Case 29: DB stores bcrypt hash (!= plaintext) that verifies."""
    from app.core.security import verify_password

    db_session.refresh(customer_user)
    stored = customer_user.password_hash
    assert stored != "customerpass"
    assert stored.startswith("$2b$")
    assert verify_password("customerpass", stored) is True
    assert verify_password("wrongpass", stored) is False


def test_no_hash_in_any_response(client, customer_headers, admin_headers, customer_user):
    """Case 30: sweep of auth/user responses contains no hash material."""
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "customer@test.com", "password": "customerpass"},
    )
    me = client.get("/api/v1/auth/me", headers=customer_headers)
    get_user = client.get(
        f"/api/v1/users/{customer_user.user_id}", headers=admin_headers
    )
    role_upd = client.patch(
        f"/api/v1/users/{customer_user.user_id}/role",
        json={"role": "customer"},
        headers=admin_headers,
    )
    for res in (login, me, get_user, role_upd):
        assert res.status_code == 200
        dumped = json.dumps(res.json()).lower()
        assert "password_hash" not in dumped
        assert "$2b$" not in dumped


def test_no_jwt_secret_leak(client, customer_user):
    """Case 31: JWT secret never appears in responses or token payload."""
    from app.core.config import get_settings
    from app.core.security import decode_access_token

    secret = get_settings().JWT_SECRET_KEY
    assert secret  # sanity: a secret is configured
    reg = client.post(
        "/api/v1/auth/register",
        json={"name": "Leak Check", "email": "leakcheck@test.com", "password": "secret123"},
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "customer@test.com", "password": "customerpass"},
    )
    for res in (reg, login):
        assert res.status_code in (200, 201)
        assert secret not in res.text
        assert "JWT_SECRET" not in res.text
    token = login.json()["data"]["access_token"]
    assert secret not in token
    payload = decode_access_token(token)
    assert payload is not None
    assert not any("secret" in str(k).lower() for k in payload.keys())


def test_no_self_assign_privileged_role(client, db_session):
    """Case 32: registration cannot self-assign privileged roles.

    role=admin/staff are rejected with 422 and no privileged account is
    created; the only created account path defaults to customer.
    """
    from app.models.user import User

    for role in ("admin", "staff", "barber", "receptionist"):
        res = client.post(
            "/api/v1/auth/register",
            json={
                "name": "Priv Check",
                "email": f"priv-{role}@test.com",
                "password": "secret123",
                "role": role,
            },
        )
        assert res.status_code == 422, role
    assert db_session.query(User).filter(User.email.like("priv-%@test.com")).count() == 0
    ok_res = client.post(
        "/api/v1/auth/register",
        json={"name": "Priv Check", "email": "priv-ok@test.com", "password": "secret123"},
    )
    assert ok_res.status_code == 201
    assert ok_res.json()["data"]["user"]["role"] == "customer"
