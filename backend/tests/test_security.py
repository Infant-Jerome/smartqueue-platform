"""Phase 11 security regression tests (isolated, no prod dependency).

Covers: security headers present, login rate limiting (429 + envelope +
non-login paths unaffected + limiter never breaks auth), and guards that
missing/invalid auth is denied. RBAC/IDOR/escalation/validation/injection
already have extensive coverage in test_auth*, test_queue*, Dub; this file
pins the two Phase 11 code changes only.
"""
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.core.rate_limit import LoginRateLimitMiddleware


def _mini_app(fail: bool = True, **kwargs):
    app = FastAPI()

    @app.post("/api/v1/auth/login")
    def login():
        if fail:
            return JSONResponse(status_code=401, content={"success": False, "message": "Invalid email or password", "data": None})
        return {"success": True, "data": {}, "message": "ok"}

    @app.get("/api/v1/services")
    def services():
        return {"success": True, "data": [], "message": "ok"}

    app.add_middleware(LoginRateLimitMiddleware, **kwargs)
    return app


def test_security_headers_present_on_api_response(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "SAMEORIGIN"
    assert r.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


def test_login_rate_limit_trips_with_envelope():
    app = _mini_app(fail=True, max_failures=5, window_seconds=60)
    tc = TestClient(app)
    codes = [tc.post("/api/v1/auth/login").status_code for _ in range(7)]
    assert codes[:5] == [401] * 5
    assert codes[5] == 429 and codes[6] == 429
    body = tc.post("/api/v1/auth/login").json()
    assert body["success"] is False and body["data"] is None
    assert "Too many attempts" in body["message"]


def test_successful_logins_never_trip_limiter():
    app = _mini_app(fail=False, max_failures=5, window_seconds=60)
    tc = TestClient(app)
    assert [tc.post("/api/v1/auth/login").status_code for _ in range(10)] == [200] * 10


def test_rate_limit_ignores_other_paths_and_methods():
    app = _mini_app(max_failures=2, window_seconds=60)
    tc = TestClient(app)
    for _ in range(5):
        assert tc.get("/api/v1/services").status_code == 200
    assert tc.post("/api/v1/auth/login").status_code == 401
    assert tc.post("/api/v1/auth/login").status_code == 401
    assert tc.post("/api/v1/auth/login").status_code == 429


def test_rate_limit_fail_open_on_broken_clock(monkeypatch):
    import app.core.rate_limit as rl

    def boom():
        raise RuntimeError("clock broken")

    monkeypatch.setattr(rl, "_clock", boom)
    app = FastAPI()

    @app.post("/api/v1/auth/login")
    def login():
        return JSONResponse({"success": True, "data": {}, "message": "ok"})

    app.add_middleware(rl.LoginRateLimitMiddleware, max_failures=1, window_seconds=60)
    assert TestClient(app).post("/api/v1/auth/login").status_code == 200


def test_unauthenticated_and_forbidden_shapes(client):
    assert client.get("/api/v1/auth/me").status_code in (401, 403)
    r = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer invalid"})
    assert r.status_code == 401
    assert r.json()["success"] is False
