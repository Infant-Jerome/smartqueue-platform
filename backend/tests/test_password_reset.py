"""Password-reset tests (Forgot Password + Email OTP + reset token).

Isolated in-memory SQLite only; OTPs are captured from the Mock email
provider outbox (``MockEmailProvider.SENT``) -- never from the API, which
must stay generic. Each test uses a distinct X-Forwarded-For IP so the
shared in-process reset limiter never leaks state between tests.
"""
import re

import pytest

from app.models.password_reset import OTP_MAX_ATTEMPTS, PasswordResetToken
from app.notifications.providers.email import MockEmailProvider

FORGOT = "/api/v1/auth/forgot-password"
VERIFY = "/api/v1/auth/verify-reset-otp"
RESET = "/api/v1/auth/reset-password"

GENERIC = "If an account exists for this email"


@pytest.fixture(autouse=True)
def _clean_outbox():
    MockEmailProvider.clear()
    yield
    MockEmailProvider.clear()


def _ip(name):
    # Unique client IP per test (reset limiter keys on this header first).
    return {"X-Forwarded-For": f"10.9.0.{abs(hash(name)) % 200 + 1}"}


def _otp_from_outbox():
    assert MockEmailProvider.SENT, "expected an OTP email to be recorded"
    body = MockEmailProvider.SENT[-1]["body"]
    m = re.search(r"\b(\d{6})\b", body)
    assert m, f"no 6-digit OTP in email body: {body[:120]}"
    return m.group(1)


def _forgot(client, email, ip):
    return client.post(FORGOT, json={"email": email}, headers=_ip(ip))


def test_forgot_existing_email_generic(client, customer_user):
    r = _forgot(client, customer_user.email, "t1")
    assert r.status_code == 200
    assert GENERIC in r.json()["message"]
    assert len(MockEmailProvider.SENT) == 1
    assert MockEmailProvider.SENT[0]["to"] == customer_user.email


def test_forgot_unknown_email_same_response_no_email(client):
    r = _forgot(client, "nobody-knows-this@test.local", "t2")
    assert r.status_code == 200
    assert GENERIC in r.json()["message"]
    assert MockEmailProvider.SENT == []


def test_otp_row_created_hashed_not_plaintext(client, customer_user, db_session):
    _forgot(client, customer_user.email, "t3")
    otp = _otp_from_outbox()
    row = db_session.query(PasswordResetToken).one()
    assert row.user_id == customer_user.user_id
    assert row.attempts == 0 and row.verified_at is None and row.used_at is None
    assert row.otp_hash != otp
    assert len(row.otp_hash) == 64  # HMAC-SHA256 hex, never the raw code


def test_otp_not_in_api_response(client, customer_user):
    r = _forgot(client, customer_user.email, "t4")
    assert r.status_code == 200
    assert "123456" not in r.text and "otp" not in r.text.lower().replace("sent", "x")


def test_verify_correct_otp_returns_reset_token(client, customer_user):
    _forgot(client, customer_user.email, "t5")
    r = client.post(VERIFY, json={"email": customer_user.email, "otp": _otp_from_outbox()}, headers=_ip("t5"))
    assert r.status_code == 200, r.text
    assert r.json()["data"]["reset_token"]


def test_verify_wrong_otp_rejected(client, customer_user):
    _forgot(client, customer_user.email, "t6")
    r = client.post(VERIFY, json={"email": customer_user.email, "otp": "000000"}, headers=_ip("t6"))
    assert r.status_code == 400


def test_verify_expired_otp_rejected(client, customer_user, db_session):
    from datetime import datetime, timedelta

    _forgot(client, customer_user.email, "t7")
    otp = _otp_from_outbox()
    row = db_session.query(PasswordResetToken).one()
    row.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db_session.commit()
    r = client.post(VERIFY, json={"email": customer_user.email, "otp": otp}, headers=_ip("t7"))
    assert r.status_code == 400


def test_verify_too_many_attempts_locked(client, customer_user):
    _forgot(client, customer_user.email, "t8")
    last = None
    for _ in range(OTP_MAX_ATTEMPTS):
        last = client.post(VERIFY, json={"email": customer_user.email, "otp": "000000"}, headers=_ip("t8"))
    assert last.status_code == 429
    # Even the correct code is now refused.
    r = client.post(VERIFY, json={"email": customer_user.email, "otp": _otp_from_outbox()}, headers=_ip("t8"))
    assert r.status_code == 429


def _verified_token(client, email, ip):
    _forgot(client, email, ip)
    r = client.post(VERIFY, json={"email": email, "otp": _otp_from_outbox()}, headers=_ip(ip))
    assert r.status_code == 200, r.text
    return r.json()["data"]["reset_token"]


def test_reset_token_one_time_use(client, customer_user):
    token = _verified_token(client, customer_user.email, "t9")
    body = {"reset_token": token, "new_password": "NewPass123", "confirm_password": "NewPass123"}
    assert client.post(RESET, json=body, headers=_ip("t9")).status_code == 200
    r = client.post(RESET, json=body, headers=_ip("t9"))
    assert r.status_code == 401


def test_reset_expired_token_rejected(client, customer_user):
    from app.core.security import create_access_token

    token = create_access_token(
        {"sub": str(customer_user.user_id), "purpose": "password_reset", "rid": 999999},
        expires_minutes=-1,
    )
    r = client.post(
        RESET,
        json={"reset_token": token, "new_password": "NewPass123", "confirm_password": "NewPass123"},
        headers=_ip("t10"),
    )
    assert r.status_code == 401


def test_reset_wrong_purpose_token_rejected(client, customer_user):
    from app.core.security import create_access_token

    token = create_access_token({"sub": str(customer_user.user_id), "role": "customer"})
    r = client.post(
        RESET,
        json={"reset_token": token, "new_password": "NewPass123", "confirm_password": "NewPass123"},
        headers=_ip("t11"),
    )
    assert r.status_code == 401


def test_reset_password_mismatch_rejected(client, customer_user):
    token = _verified_token(client, customer_user.email, "t12")
    r = client.post(
        RESET,
        json={"reset_token": token, "new_password": "NewPass123", "confirm_password": "OtherPass123"},
        headers=_ip("t12"),
    )
    assert r.status_code == 422


def test_password_changed_old_dead_new_works(client, customer_user):
    token = _verified_token(client, customer_user.email, "t13")
    body = {"reset_token": token, "new_password": "BrandNew123", "confirm_password": "BrandNew123"}
    assert client.post(RESET, json=body, headers=_ip("t13")).status_code == 200
    assert client.post("/api/v1/auth/login", json={"email": customer_user.email, "password": "customerpass"}).status_code == 401
    r = client.post("/api/v1/auth/login", json={"email": customer_user.email, "password": "BrandNew123"})
    assert r.status_code == 200


def test_second_request_supersedes_first_otp(client, customer_user, db_session):
    from datetime import datetime, timedelta

    _forgot(client, customer_user.email, "t14")
    first_otp = _otp_from_outbox()
    # Fast-forward past the resend cooldown, then request again.
    for row in db_session.query(PasswordResetToken).all():
        row.created_at = datetime.utcnow() - timedelta(seconds=120)
    db_session.commit()
    _forgot(client, customer_user.email, "t14")
    assert len(MockEmailProvider.SENT) == 2
    r = client.post(VERIFY, json={"email": customer_user.email, "otp": first_otp}, headers=_ip("t14"))
    assert r.status_code == 400
    r = client.post(VERIFY, json={"email": customer_user.email, "otp": _otp_from_outbox()}, headers=_ip("t14"))
    assert r.status_code == 200


def test_resend_cooldown_enforced(client, customer_user):
    _forgot(client, customer_user.email, "t15")
    r = _forgot(client, customer_user.email, "t15")
    assert r.status_code == 429


def test_reset_request_rate_limiter_trips():
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    from app.core.rate_limit import ResetRequestRateLimitMiddleware

    app = FastAPI()

    @app.post("/api/v1/auth/forgot-password")
    def forgot():
        return JSONResponse({"success": True, "message": "ok", "data": None})

    app.add_middleware(ResetRequestRateLimitMiddleware, max_requests=3, window_seconds=60)
    tc = TestClient(app)
    codes = [tc.post("/api/v1/auth/forgot-password").status_code for _ in range(5)]
    assert codes[:3] == [200] * 3
    assert codes[3] == 429 and codes[4] == 429
    body = tc.post("/api/v1/auth/forgot-password").json()
    assert body["success"] is False and body["data"] is None


def test_existing_login_registration_rbac_intact(client, customer_user, admin_user, db_session):
    from tests.conftest import auth_headers

    # Login still works.
    assert client.post("/api/v1/auth/login", json={"email": customer_user.email, "password": "customerpass"}).status_code == 200
    # Registration still works.
    r = client.post(
        "/api/v1/auth/register",
        json={"name": "Reset Flow", "email": "resetflow@test.local", "password": "SomePass123"},
    )
    assert r.status_code == 201, r.text
    # RBAC still works: customer denied admin role path, admin allowed.
    chead = auth_headers(client, customer_user.email, "customerpass")
    assert client.patch("/api/v1/auth/users/1/role", json={"role": "admin"}, headers=chead).status_code == 403
    ahead = auth_headers(client, admin_user.email, "adminpass")
    assert client.get("/api/v1/auth/me", headers=ahead).status_code == 200
