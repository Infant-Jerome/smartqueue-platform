# SmartQueue — Architecture

## Overview

SmartQueue is a client–server web application split into a FastAPI backend and a React SPA frontend.

- The **backend** exposes a versioned REST API (`/api/v1`), handles JWT authentication, business logic (booking, queue), and persistence via SQLAlchemy.
- The **frontend** is a React SPA served by Vite in development, which proxies `/api` requests to the backend. In production the API could be served behind the same origin or a reverse proxy.

## High-level data flow

```
Browser (React SPA)
        │
        │  HTTP /api/v1/*  (JSON) ── proxied by Vite (dev)
        ▼
   FastAPI app (app.main:app)
        │
        ├─ CORS middleware
        ├─ routers: /auth /services /barbers /appointments /queue
        │
        ├─ Pydantic schemas   (request/response validation)
        ├─ Security layer     (JWT + bcrypt, api/deps.py)
        ▼
   SQLAlchemy ORM  →  Database (SQLite / MySQL)
```

## Component breakdown

### Backend layers

| Layer | Location | Responsibility |
| --- | --- | --- |
| API routes | `app/api/v1/` | HTTP endpoints, status codes, authorization wiring |
| Dependencies | `app/api/deps.py` | Current-user resolution and role guards |
| Core | `app/core/` | Settings, engine/session, password hashing & JWT |
| Models | `app/models/models.py` | `User`, `Barber`, `Service`, `Appointment`, `QueueEntry` |
| Schemas | `app/schemas/schemas.py` | Pydantic request/response models |
| Entrypoint | `app/main.py` | App factory, CORS, router registration, `/api/health` |

### Frontend structure

| Path | Responsibility |
| --- | --- |
| `services/api.js` | Axios instance with JWT injection and 401 redirect |
| `context/AuthContext.jsx` | Auth state + login/register/logout |
| `components/ProtectedRoute.jsx` | Route guard by auth + role |
| `pages/` | Login, Register, Dashboard, Services, Barbers, Book, Queue, Admin |

## Key design decisions

1. **JWT auth with role claims.** Tokens embed `sub` (user id) and `role`. Role checks are enforced in `require_role(...)` rather than only in the UI, so the API is the source of truth.
2. **Double-booking prevention.** `Appointment` has a unique constraint on `(barber_id, appointment_date, appointment_time)` plus a stricter application-level check in `create_appointment` that ignores cancelled/no-show slots.
3. **Queue as a derived entity.** Each appointment creates a `QueueEntry`. Queue numbers are assigned per-day (1, 2, 3, ...) based on existing entries for that date.
4. **SQLite by default, MySQL optional.** `DATABASE_TYPE` in `.env` switches the engine. All schema is defined via SQLAlchemy models, and Alembic is configured for migrations.
5. **CORS allows the Vite dev origin.** In production, `CORS_ORIGINS` should be narrowed to the real frontend domain.

## Security

- Passwords hashed with bcrypt.
- JWT signed with `JWT_SECRET_KEY` (HS256); extend expiry via `JWT_EXPIRE_MINUTES`.
- Endpoint authorization layered by role: public → authenticated → admin/staff.
- In production: rotate `JWT_SECRET_KEY`, set `DEBUG=False`, and use MySQL over SQLite.

## Testing strategy

Phase 8 added a pytest suite (`backend/tests/`):

- **Unit** — password hashing & JWT round-trips, queue-number assignment.
- **Integration/API** — TestClient fixture over an isolated temp SQLite DB covering auth, services, barbers, appointments (including double-booking conflict), and queue lifecycle (serve → complete).

See [Rubber-stamp check](../backend/tests/README.md) for how to run them.

## Contributing workflow

1. Add/change a model → write an Alembic revision (or rely on `create_all` in dev).
2. Update the Pydantic schema if the API contract changes.
3. Add/adjust a route in `app/api/v1/`.
4. Add a test in `backend/tests/`; run `pytest -v`.
5. Update the CHANGELOG.