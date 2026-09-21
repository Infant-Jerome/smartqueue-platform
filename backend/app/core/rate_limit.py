"""Minimal production safety middleware (Phase 11).

- Security headers: static, safe values that do not affect API/Swagger
  behavior (no CSP: inline scripts in /docs must keep working; no HSTS:
  TLS is terminated at the hosting edge).
- Login rate limiting: in-memory sliding window per client IP on the two
  credential endpoints only. Bounded, never raises, fails open on error.
  Single-instance scope (documented limitation; use a shared store if the
  deployment ever scales horizontally).
"""
import time
from collections import deque

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

LOGIN_PATHS = frozenset({"/api/v1/auth/login", "/api/v1/auth/register"})

# Indirection for tests (monkeypatch rl._clock, never the global clock).
_clock = time.monotonic


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


class LoginRateLimitMiddleware(BaseHTTPMiddleware):
    """429 after >max_failures failed (401) logins per window per client IP.

    Only failed attempts count, so legitimate login bursts (including the
    project's own test suite, which shares one TestClient IP) are never
    throttled — only credential guessing is.
    """

    def __init__(self, app, max_failures: int = 20, window_seconds: int = 60):
        super().__init__(app)
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._hits: dict[str, deque] = {}

    def _client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        client = request.client
        return client.host if client else "unknown"

    def clear(self) -> None:
        self._hits.clear()

    async def dispatch(self, request: Request, call_next):
        try:
            if request.method != "POST" or request.url.path not in LOGIN_PATHS:
                return await call_next(request)
            now = _clock()
            key = f"{self._client_ip(request)}"
            bucket = self._hits.setdefault(key, deque())
            cutoff = now - self.window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.max_failures:
                return JSONResponse(
                    status_code=429,
                    content={"success": False, "message": "Too many attempts. Please try again later.", "data": None},
                )
            response = await call_next(request)
            if response.status_code == 401:
                bucket.append(now)
            return response
        except Exception:
            # Never break authentication on limiter failure.
            return await call_next(request)
