# SmartQueue Backend

FastAPI backend for the SmartQueue barbershop appointment & queue platform.
REST API at `/api/v1`, JWT auth (python-jose + bcrypt), SQLAlchemy 2.0 ORM,
Alembic migrations, Pydantic v2 schemas.

> Scope: Phases 1–4 + 5A + 5B + 5C (implemented). This document describes what is **implemented**
> (auth in §10, booking rules in §11, queue engine in §12, read-only realtime in §13, notifications in §14, SAWTE estimation in §15). Anything not listed here — including
> the future-phase items at the bottom — is **not** claimed as implemented.

## 1. Architecture

```text
Browser / Frontend (React SPA)
        │  HTTP JSON  /api/v1/*  +  WS /api/v1/ws/queue/{salon_id} (Phase 5A, read-only push)
        ▼
FastAPI app (app.main:app)
        ├─ CORS middleware (comma-separated CORS_ORIGINS)
        ├─ Routers (app/api/v1/): /auth /services /barbers /appointments /queue /availability + WS /ws/queue/{salon_id}
        ├─ Deps (app/api/deps.py): current-user resolution, require_role(...) guards (REST); WS uses ?token= JWT (see §13)
        ├─ Services (app/services/): appointments_service, queue_service, queue_events (post-commit publisher)
        ├─ WS (app/ws/): manager (single-instance fan-out), events (envelopes + sanitizer)
        ├─ Schemas (app/schemas/schemas.py): Pydantic v2 request/response validation
        ├─ Core (app/core/): config, engine/session, password hashing + JWT, envelope helpers
        ▼
SQLAlchemy ORM (app/models/*.py) → Database (SQLite / MySQL / Postgres)
```

| Layer | Location | Responsibility |
| --- | --- | --- |
| Entrypoint | `app/main.py` | App factory, CORS, router registration (`/api/v1`), lifespan startup (`create_all`), `/api/health` envelope + `SELECT 1` DB probe |
| API routes | `app/api/v1/` | `auth.py`, `services.py`, `barbers.py`, `appointments.py`, `queue.py`, `availability.py`, `queue_ws.py` (`WS /ws/queue/{salon_id}`); thin handlers, status codes, auth wiring; aggregated in `router.py` |
| Dependencies | `app/api/deps.py` | Current-user resolution from JWT, role guards (`require_role`) — API is the source of truth, not the UI |
| Services | `app/services/` | Booking rules (slot validation, double-booking check, per-day queue number), queue lifecycle (waiting → serving → completed + linked appointment status + history + estimates), `queue_events` post-commit publisher (forwards committed positions/waits, never computes) |
| Notifications | `app/notifications/` + `app/api/v1/notifications.py` | Phase 5B post-commit consumer of `queue_events` (no second bus): per-channel fan-out (mock default), templates, prefs, durable `notifications` table; history GET only (§14); failures never roll back the queue |
| WS | `app/ws/` | `manager.py` (process-local singleton fan-out, single-instance), `events.py` (`{event,data}` envelopes + allowlist sanitizer), `schemas.py` (wire validation) |
| Core | `app/core/` | `config.py` (settings, `DATABASE_URL` override), `database.py` (engine/session/`Base`/`get_db`), `security.py` (bcrypt + JWT), `response.py` (uniform `{success, data, message}` envelope) |
| Models | `app/models/models.py` | SQLAlchemy tables (see §5) |
| Schemas | `app/schemas/schemas.py` | Pydantic request/response models |
| Seed | `seed.py` | Sample data: admin + customer, 3 barbers, 5 services |

Key design decisions (implemented):

1. **JWT auth with role claims.** Tokens embed `sub` (user id) and `role`. Enforced server-side via `require_role(...)`.
2. **Overlap prevention (Phase 3).** Booking enforces half-open range overlap
   (`start_a < end_b and end_a > start_b`, so back-to-back slots are legal)
   per barber+date and per customer+date, ignoring `cancelled`/`no_show` rows
   — no slot `UNIQUE` (a plain constraint cannot express ranges or
   ignore-by-status). Conflicts return `409` with a barber-taken vs
   own-overlap message (see §11). The composite index
   `ix_appointment_barber_date` keeps the per-day lookup indexed.
3. **Server-derived slots (Phase 3).** `end_time = start_time +
   service.duration_minutes` — clients send no `end_time`/`customer_id`
   (`422` if smuggled). Salon hours and `barber_availability` windows are
   enforced (`400`); reschedule re-derives and re-checks (see §11).
3. **Queue as a derived entity.** Each appointment inserts one `Queue` row (`waiting`); queue positions are max+1 per (date[, barber]) (`queue_position`); wait estimates are Phase 5C SAWTE per (date, barber) scope — deterministic history-based algorithmic/adaptive/historical moving-average estimation (`serving remainder + sum ahead`, latest-5 window else `Service.duration_minutes` fallback, see §15); every queue op writes `AppointmentStatusHistory` and pushes post-commit WS events (see §13).
4. **Uniform envelope.** All responses (including errors and `/api/health`) use `{success, data, message}`.
5. **Startup + migrations.** Lifespan handler runs `Base.metadata.create_all`; the same baseline schema is captured as an Alembic migration for managed environments (see §4).

## 2. Environment variables

Configured via `.env` in `backend/` (see `backend/.env.example`; root `.env.example` mirrors it).
`DATABASE_URL` takes precedence when set; otherwise the field-based settings apply.
Only `JWT_SECRET_KEY` is required — everything else has a default. Never commit real secrets.

| Variable | Description | Required | Default |
| --- | --- | --- | --- |
| `DATABASE_URL` | Full DB URL override (e.g. `postgresql+psycopg2://USER:PASSWORD@HOST:5432/DB` on Render). Takes precedence when set | N | — (falls back below) |
| `DATABASE_TYPE` | Dialect fallback when `DATABASE_URL` is empty: `sqlite` or `mysql` | N | `sqlite` |
| `DATABASE_HOST` | Host (MySQL only) | N | `localhost` |
| `DATABASE_PORT` | Port (MySQL only) | N | `3306` |
| `DATABASE_USER` | User (MySQL only) | N | `root` |
| `DATABASE_PASSWORD` | Password (MySQL only) | N | (empty) |
| `DATABASE_NAME` | Database name (MySQL only) | N | `smartqueue_db` |
| `JWT_SECRET_KEY` | Secret used to sign/verify JWTs — rotate in production | Y | placeholder |
| `JWT_ALGORITHM` | JWT algorithm | N | `HS256` |
| `JWT_EXPIRE_MINUTES` | Access-token lifetime in minutes | N | `60` |
| `APP_NAME` | Application display name (returned by `/api/health`) | N | `SmartQueue - Barbershop Platform` |
| `APP_VERSION` | Version string (returned by `/api/health`, shown in `/docs`) | N | `1.0.0` |
| `DEBUG` | Debug mode (`true`/`false`; also enables SQL echo) | N | `True` |
| `CORS_ORIGINS` | Comma-separated allowed origins, e.g. `http://localhost:5173,http://localhost:3000` | N | `http://localhost:5173,http://localhost:3000` |
| `NOTIFS_ENABLED` | Master switch for Phase 5B fan-out | N | `True` |
| `APPROACHING_THRESHOLD` | `queue.updated` → `queue_approaching` only when `queue_position <= threshold` | N | `2` |
| `EMAIL_ENABLED` / `PUSH_ENABLED` / `SMS_ENABLED` | Real-provider gates — `false` = mock path (shipped default); real stubs need creds (see §14) | N | `false` |
| `EMAIL_HOST/PORT/USER/PASS/FROM`, `PUSH_*`, `SMS_*` | Real-provider placeholders only — empty by default, never real secrets | N | empty |

## 3. Database setup

| Environment | Database | How |
| --- | --- | --- |
| Local dev (default) | SQLite file `backend/smartqueue.db` | Leave `DATABASE_URL` empty and `DATABASE_TYPE=sqlite`. Tables auto-created on startup; run `python seed.py` once for demo data |
| Prod (MySQL) | MySQL via PyMySQL | Set `DATABASE_TYPE=mysql` + `DATABASE_HOST/PORT/USER/PASSWORD/NAME` in `backend/.env` |
| Prod (Postgres, e.g. Render) | Postgres via `psycopg2-binary` | Set full `DATABASE_URL=postgresql+psycopg2://...` — takes precedence over all field-based settings |
| Tests | Isolated in-memory SQLite | Automatic via `backend/tests/conftest.py` (`sqlite://` + `StaticPool`); never touches `smartqueue.db`, no setup needed |

Drivers are in `backend/requirements.txt`: `pymysql` (MySQL), `psycopg2-binary` (Postgres).
Non-SQLite URLs use a pooled engine with `pool_pre_ping`/`pool_recycle` (`app/core/database.py`).

## 4. Migrations (Alembic)

Revisions: `ebc12f99c799_initial_schema.py` (initial baseline) →
`f7ad2ddb6a36_add_salons_and_phase_1_model_updates.py` (adds `salons` plus
salon/user links on barbers/services) →
`eb348e90a283_canonicalize_pks_retire_legacy.py` (canonical PK/FK names,
retires legacy columns, creates `barber_availability` +
`appointment_status_history`, explicit `ix_*` indexes including
`ix_appointment_barber_date` and `ix_availability_barber_date`). The canonical
8-table schema is defined in `app/models/*.py` (see §8);
`app/models/models.py` is now a deprecated re-export shim that defines no
tables (`QueueEntry = Queue` alias only). Verified `upgrade head` on a fresh
SQLite DB plus a `downgrade -1` / `upgrade head` cycle and a clean
`alembic check` (no drift) — no further migration needed; startup
`create_all` keeps dev simple.

```bash
cd backend
alembic upgrade head                                  # apply all migrations (incl. baseline)
alembic revision --autogenerate -m "describe change" # create a migration after model edits
alembic upgrade head                                  # apply it
alembic downgrade -1                                  # roll back one revision
alembic history                                       # list revisions
alembic current                                       # show current revision
```

Contributing workflow: model change → `alembic revision --autogenerate` →
update Pydantic schema if the contract changes → update route → add test →
`pytest -v` → update CHANGELOG.

Note: `alembic.ini` ships with a local `sqlalchemy.url` placeholder; managed
deploys apply `alembic upgrade head` at start (see `render.yaml`).

## 5. Local run

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate   |  Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then set JWT_SECRET_KEY (required)
python seed.py              # sample data: admin + customer + barbers + services
uvicorn app.main:app --reload --port 8000
```

- API base: `http://localhost:8000/api/v1`
- Health: `http://localhost:8000/api/health` (envelope + `database: up/down`; HTTP 503 when DB is down)
- Seeded demo accounts: `admin@salon.com` / `Admin@123`, `jerome@salon.com` / `Jerome@123`

## 6. Testing

```bash
cd backend
pytest -v                   # or: python -m pytest -v
```

- Config: `backend/pytest.ini` (`testpaths = tests`).
- Fixtures (`tests/conftest.py`): per-test in-memory SQLite engine, scoped session,
  `TestClient` with `get_db` overridden, `admin_user`/`customer_user`,
  `admin_headers`/`customer_headers`, `seeded_data` (one barber + one service).
- Coverage: auth (register/duplicate/login/wrong-password/`/me`), services &
  barbers (public read, admin-only write, customer 403), appointments (create,
  past-date rejection, double-booking 409, cancel-only rules, per-user scope),
  queue (staff-only access, `my-position`, serve → complete lifecycle).
- Details: `backend/tests/README.md`.

## 7. API docs (Swagger / ReDoc)

Auto-generated by FastAPI once the backend is running — no extra setup:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

All business endpoints live under `/api/v1`
(`auth`, `services`, `barbers`, `appointments`, `queue`, `availability`) plus
`WS /api/v1/ws/queue/{salon_id}?token=&barber_id=&date=` (read-only push, §13); health check at `/api/health`.

## 8. Model overview

Implemented schema: **8 tables / 8 entities** in `app/models/*.py`
(re-exported via `app.models`; mirrored by `docs/backend.md` §7).
Canonical entity class is `Queue` (table `queue`) — never `QueueEntry`.
No `appointments.id` / `queue.id` claims: PKs are `appointment_id` / `queue_id`.
If any other document mentions a different entity count, this section —
which matches the canonical models — is authoritative.

| Entity (table) | Key columns | Relationships |
| --- | --- | --- |
| `User` (`users`) | `user_id` PK; `email` unique+indexed; `password_hash` (bcrypt); `name`, `phone`, `role` (`customer`/`barber`/`admin`/`staff`), `created_at`/`updated_at` | 1:N → `Appointment` (via `customer_id`); 1:1 → barber profile |
| `Salon` (`salons`) | `salon_id` PK; `name`, `address`, `phone`, `opening_time`/`closing_time` (seeded 09:00–18:00; slots must fit inside — `400` otherwise, see §11), `status`, `created_at`/`updated_at` | 1:N → `Barber`, `Service`, `Appointment`, `Queue` (no delete cascades) |
| `Barber` (`barbers`) | `barber_id` PK; `user_id` → `users.user_id` (SET NULL, nullable); `salon_id` → `salons.salon_id` (SET NULL, nullable); `name`, `specialization`, `phone`, `experience_years` (≥ 0), `availability_status`, `created_at`/`updated_at` | N:1 → `User`/`Salon`; 1:N → `Appointment`, `BarberAvailability`, `Queue` (no delete cascade on appointments) |
| `Service` (`services`) | `service_id` PK; `salon_id` → `salons.salon_id` (SET NULL, nullable); `service_name`, `description`, `duration_minutes` (> 0), `price` (`Numeric(10,2)` ≥ 0), `status`, `created_at`/`updated_at` | N:1 → `Salon`; 1:N → `Appointment` (no delete cascade) |
| `BarberAvailability` (`barber_availability`) | `availability_id` PK; `barber_id` → `barbers.barber_id` (CASCADE); `date`, `start_time`/`end_time` (`start_time < end_time`, single-day — midnight-crossing rejected), `status` (`available`/`unavailable`/`off`), `created_at`/`updated_at`; composite index `ix_availability_barber_date` (`barber_id`, `date`) | N:1 → `Barber`. Full CRUD at `/api/v1/availability` (admin / staff / owner-barber writes; staff delete deactivates); booking validates slots against windows when rows exist (see §11) |
| `Appointment` (`appointments`) | `appointment_id` PK; `customer_id` → `users.user_id` (CASCADE); `salon_id` → `salons.salon_id` (SET NULL, nullable); `barber_id` → `barbers.barber_id` (CASCADE); `service_id` → `services.service_id` (CASCADE); `appointment_date`, `start_time`/`end_time` (`start_time < end_time`, server-derived from `service.duration_minutes`); `status` (default `booked`); `booking_type` (`online`/`walk_in`, default `online`); `actual_duration_minutes` (nullable `Integer`, Phase 5C SAWTE measured minutes — `NULL` = unknown, written once on complete, see §15); `created_at`/`updated_at` | N:1 → `User`/`Salon`/`Barber`/`Service`; 1:0..1 → `Queue` (delete-orphan); 1:N → `AppointmentStatusHistory` (delete-orphan, written on create + every transition). No slot `UNIQUE` — half-open range-overlap checks ignore `cancelled`/`no_show` rows (see §11) |
| `Queue` (`queue`) | `queue_id` PK; `appointment_id` → `appointments.appointment_id` (CASCADE, unique — one row per appointment); `salon_id` → `salons.salon_id` (SET NULL, nullable); `barber_id` → `barbers.barber_id` (CASCADE); `queue_position` (1-based, ≥ 1, per-day max+1 — see §12); `joined_at`; `estimated_wait_minutes` (nullable; `service.duration_minutes` at booking); `status` (`waiting`/`serving`/`completed`, plus mirrored `cancelled`/`no_show` — see §12); `updated_at` | N:1 → `Appointment`/`Salon`/`Barber` |
| `AppointmentStatusHistory` (`appointment_status_history`) | `history_id` PK; `appointment_id` → `appointments.appointment_id` (CASCADE); `old_status` (nullable — creation row is `None → booked`), `new_status`, `changed_at` (indexed); append-only, one row per status transition/cancel (see §11) | N:1 → `Appointment` |

Relationship summary: `users 1:N appointments` (via `customer_id`),
`salons 1:N barbers/services/appointments/queue`, `barbers 1:N appointments`,
`services 1:N appointments`, `appointments 1:0..1 queue`,
`appointments 1:N status history`, `barbers 1:N availability`.

Transitional note: routes/services/schemas use the canonical names
(`appointment_id`, `customer_id`, `queue_position`,
`estimated_wait_minutes`, `Queue`); `QueueEntry` survives only as a
deprecated alias in the `app/models/models.py` shim. Old test payloads that
still send `end_time`/`appointment_time` now get `422` (`extra="forbid"`).

## 9. Deliberately FUTURE phase — Phase 5C boundary (not implemented)

These are **out of scope through Phase 5B** (see also `problemstatement.md`
§9). Phases 3–4 implement the booking rules in §11 and the queue engine in
§12, Phase 5A adds read-only realtime in §13, and Phase 5B adds notifications
in §14; the items below are named only so readers do not assume they exist:

- **Appointment engine (advanced)** — beyond current single-slot booking with
  server-derived slots, hours/window validation, availability CRUD,
  reschedule, and history writes (§11): multi-barber availability search,
  recurring appointments, deposits/holds, calendar sync.
- **Queue engine (advanced)** — beyond the current waiting → serving →
  completed lifecycle with per-day positions, `serve-next`, one-active
  guard, history on every op (§12) and read-only WS push (§13):
  priority queues, no-show prediction handling,
  multi-branch queues (single salon scope today).
- **Notifications (Phase 5B — implemented, see §14).** Landed: post-commit
  fan-out with mock-default providers, history GET only, bounded retry
  (max 3). Still out: real gateway delivery (mock validated only),
  user-managed preference endpoints, multi-language templates.
- **SAWTE estimation (Phase 5C — implemented, see §15).** Landed: deterministic history-based algorithmic/adaptive/historical moving-average estimation (`estimate = serving_remaining + sum(ahead)`, latest-5 window, `Service.duration_minutes` fallback, `LOW`/`MEDIUM`/`HIGH` data-availability confidence). **Not** ML — no models, training pipelines, or inference endpoints exist. Still out: demand analytics, BI dashboards.

Also out of scope (per problem statement): payments, customer ratings/reviews,
multi-branch support, mobile apps.

## 10. Authentication & authorization (Phase 2)

Implemented in `app/api/v1/auth.py` + `app/api/deps.py` +
`app/core/security.py`. All responses (including auth errors) use the
uniform `{success, data, message}` envelope.

### Endpoints (all under `/api/v1/auth`)

| Method & path | Auth | Success | Errors |
| --- | --- | --- | --- |
| `POST /api/v1/auth/register` | Public. Body: `name`, `email`, `password`, optional `phone` | `201` + `{access_token, token_type: "bearer", user}` | `400` email already registered; `422` validation failure |
| `POST /api/v1/auth/login` | Public. Body: `email`, `password` | `200` + `{access_token, token_type: "bearer", user}` | `401` invalid email or password |
| `GET /api/v1/auth/me` | Bearer token required | `200` + current `UserResponse` | `401` missing/invalid/expired token, bad payload, or user not found |

### JWT

- `HS256` (default `JWT_ALGORITHM`), signed with `JWT_SECRET_KEY` — rotate
  in production, never commit.
- `exp` claim set at issue from `JWT_EXPIRE_MINUTES` (default `60`);
  expired tokens are rejected with `401`.
- Claims `sub` (= `User.user_id` as string) + `role`; the user row is
  re-loaded by `sub` on every authenticated request, so the DB — not the
  token — is the source of truth.
- Passwords stored as bcrypt `password_hash` only; malformed hashes verify
  as non-match, never raise.

### Default role & no self-assign

- `POST /register` **always** creates `role="customer"`: `UserCreate` has no
  `role` field, so callers cannot self-assign `admin`/`staff`/`barber`.
- Canonical roles (`UserRole`): `customer` / `barber` / `admin` / `staff`.
  "Receptionist" is the operational label for the `staff` role (front-desk
  queue operators), not a separate role value.

### RBAC matrix

Server-side `require_role(...)` guards: `401` unauthenticated,
`403` insufficient permissions. `barber` is login-capable (optionally
linked 1:1 to a `Barber` profile via `Barber.user_id`) but has no staff
powers on its own.

| Area | customer | barber | receptionist (`staff`) | admin |
| --- | --- | --- | --- | --- |
| `POST /auth/register`, `POST /auth/login` | Public | Public | Public | Public |
| `GET /auth/me` | Own profile | Own profile | Own profile | Own profile |
| `GET /services`, `GET /barbers` (list + detail) | Public | Public | Public | Public |
| `POST/PUT/DELETE /services`, `/barbers` | `403` | `403` | `403` | Allowed |
| `GET /appointments` | Own only | Assigned only | All | All |
| `GET /appointments/{id}` | Own only (`403` otherwise) | Assigned only (`403` otherwise) | Any | Any |
| `POST /appointments` (`{barber_id, service_id, appointment_date, start_time, salon_id?, booking_type?}`; `end_time`/`customer_id` in body → `422`) | Own bookings (`201`; `404` unknown; `400` past/inactive/cross-salon/hours/window; `409` overlap; `?customer_id=` → `403`) | Same as customer | Same, plus `?customer_id=` on-behalf | Same, plus `?customer_id=` on-behalf |
| `PUT /appointments/{id}` (reschedule + `status?`) | Own + cancel-only (`403` otherwise) | Assigned (terminal rows `400`) | Any | Any |
| `DELETE /appointments/{id}` (= cancel, not hard delete) | Own (`400` if completed) | Assigned | Allowed | Allowed |
| `GET /queue`, `GET /queue/current`, `PUT /queue/{id}`, `POST /queue/serve-next`, `POST /queue/{id}/serve|complete|skip` | `403` | Own barber scope only (`403` cross-barber) | Allowed | Allowed |
| `GET /queue/my-position` | Own position | Own position | Own position | Own position |
| `WS /ws/queue/{salon_id}?token=&barber_id=&date=` (read-only push, §13) | Own-scope snapshot only | Own `barber_id` only (`4403` otherwise) | Full salon scope | Full salon scope |
| `GET /notifications` (history only, §14 — no send endpoint) | Own rows only | `403` | `403` | All rows |
| `/availability` | Any authenticated read; write = admin / staff / owner-barber (`403` customer / non-owner barber); delete = admin & owner hard-delete, staff deactivates | Same | Same | Same |

### Swagger / Bearer

- `HTTPBearer` in `app/api/deps.py` wires the Swagger UI (`/docs`)
  **Authorize** button: paste `<access_token>`, requests send
  `Authorization: Bearer <token>`. Same scheme in ReDoc (`/redoc`) and
  `/openapi.json`.

### Seed logins (dev only)

`python seed.py` is dev/demo only with a production refusal guard. It
seeds four logins (emails printed, passwords never printed; override via
`SEED_*_EMAIL` / `SEED_*_PASSWORD`): `admin@salon.com` (`admin`),
`jerome@salon.com` (`customer`), `arun@salon.com` (`barber`, linked to a
`Barber` profile), `reception@salon.com` (`staff` — receptionist).
It also seeds the demo salon (hours 09:00–18:00), one `barber_availability`
window (first barber, today, 09:00–18:00) covering the demo appointment
(10:00–10:30), its `waiting` queue row (`queue_position=1`), and the
creation history row (`None → booked`).
Also listed in `docs/backend.md` §9.

### Scope note

Auth covers identity + role guards only (REST `Bearer`, WS `?token=` — §13).
The advanced appointment engines (multi-barber search, recurring bookings)
are **still Phase 5 future** (see §9). Phase 3
booking rules are in §11; the Phase 4 queue engine is in §12; Phase 5A
read-only realtime is in §13.

## 11. Booking & availability (Phase 3 — implemented)

Booking engine in `app/services/appointments_service.py`; HTTP contract in
`app/api/v1/appointments.py`. Normative rule detail lives in
`docs/backend.md` §10. Summary:

- **Availability endpoints: implemented.** CRUD at `/api/v1/availability`
  (`{barber_id, date, start_time, end_time, status?}`; `status` in
  `available`/`unavailable`/`off`; single-day windows, `409` on overlap,
  `422` outside salon hours). Reads: any authenticated (optional
  `barber_id`/`date` filters). Writes: admin, staff/receptionist, and the
  owning barber (`403` otherwise, incl. barber-vs-barber). Delete: admin and
  owner hard-delete; staff deactivates (`status='unavailable'`). Booking
  validates against these windows when rows exist for the barber+date.
- **Booking flow:** `POST /api/v1/appointments` takes `{barber_id,
  service_id, appointment_date, start_time, salon_id?, booking_type?}` —
  `end_time`/`customer_id` in the body → `422`. Salon/barber/service checks
  (`404`/`400`, incl. cross-salon belonging) → past-date and same-day
  past-time guards (`400`) → **server-derived** `end_time = start_time +
  service duration` → `booking_type` whitelist (`422`) → salon-hours and
  availability-window checks (`400`) → half-open overlap checks (`409`,
  ignoring `cancelled`/`no_show`) → transactional
  appointment + `waiting` queue row + `None → booked` history row → `201`
  with embedded `queue_position`. Staff/admin may pass `?customer_id=` to
  book on behalf; customers get `403` for it.
- **Reschedule:** `PUT` with `appointment_date?`/`start_time?` re-derives
  `end_time` and re-runs all slot checks excluding the row itself;
  `completed`/`cancelled` rows are immutable (`400`).
- **Status/history/cancel:** transition map enforced (`400` illegal jumps);
  every transition appends history; derived queue row mirrors status;
  `DELETE` is **cancel** (idempotent `200` when already cancelled, `400`
  when completed) — not a hard delete.
- **`409` only for overlap + queue guards** (create + reschedule overlap;
  serve/serve-next one-active clash, terminal transitions, double-join),
  distinguished by message;
  failed bookings write nothing.
- **Phase 5A realtime:** `queue_events` publishes post-commit; WS pushes
  `queue.created/serving/completed/skipped/cancelled/updated` (see §13).
- **Phase 5B notifications:** same post-commit `queue_events` feed drives
  per-user records; queue never rolls back on notification failure (see §14).
- **Phase 5C boundary:** multi-barber search, recurring bookings,
  deposits/holds, calendar sync, priority/multi-branch queues,
  AI prediction (see §9). WS realtime (§13) + mock-default notifications (§14) are landed.

## 12. Queue engine (Phase 4 — implemented, Phase 5A guards landed)

Engine in `app/services/queue_service.py`; contract in
`app/api/v1/queue.py`; normative detail in `docs/backend.md` §11.
Summary (appointment `in_progress` ↔ queue `serving`):

- **Lifecycle:** booking inserts one `waiting` queue row; `waiting →
  serving/no_show/cancelled`, `serving → completed/cancelled`; `waiting →
  completed` directly is `400`, terminal-out is `409`, unknown `PUT`
  status is `422`. Endpoints: `POST /queue/serve-next`
  (`{barber_id*, salon_id?}`), `POST /queue/{id}/serve|complete|skip`,
  `PUT /queue/{id}`, `GET /queue` (filters `salon_id/barber_id/status/
  date`), `GET /queue/current` (`200` + `null` when empty),
  `GET /queue/my-position`. `cancelled` / `no_show` are terminal branches.
- **Position:** 1-based max+1 per (date[, barber]) (`_next_position_for_scope`),
  else `1`; `ck_queue_position_positive`; no renumbering/compaction;
  `appointment_id` UNIQUE double-join guard (`409`).
- **Scoping:** `appointment_id` unique CASCADE, `salon_id` nullable
  SET NULL, `barber_id` not null CASCADE. `GET /queue` lists active
  (`waiting`/`serving`/`in_progress`, `queue_position ASC`) with optional
  scope filters.
- **Serve-next / one-active (landed):** `POST /serve-next` serves the
  smallest `waiting` position for (today, barber[+ salon]); `404` when
  empty; **`409` one-active guard** when a `serving` row is already active
  for the (date, barber) scope — enforced in `serve`, `serve-next`, and
  every `_commit_transition` into `serving`.
- **Wait:** Phase 5C SAWTE per (date, barber) scope — deterministic history-based algorithmic/adaptive/historical moving-average estimation: `estimate = serving_remaining + sum(ahead)` where `expected` = latest-5 average else `Service.duration_minutes` fallback (missing → `0`), `serving_remaining = max(0, ceil(expected − elapsed))`, ahead = `waiting` rows with lower position, all `ceil`ed; `my-position` returns the same scope math + `currently_serving` + `confidence` (see §15); never ML.
- **Sync/history (landed):** every queue op goes through
  `_commit_transition` (queue + appointment + `AppointmentStatusHistory`
  + estimates, one commit; rollback on failure) — serve/complete/skip/
  PUT all write history; appointment-side transitions likewise.
  `DELETE /appointments/{id}` cancels via `cancel_queue_for_appointment`
  (idempotent on terminal rows).
- **RBAC:** operate = non-customer (customer → `403`) + barber own-scope
  (`403` cross-barber), `my-position` any authenticated.
  **Errors:** `404` unknown entry / empty serve-next scope; `409` queue
  guards (one-active clash, terminal, double-join) + booking overlap;
  `400` illegal edges; `422` bad `PUT`/serve-next body.
- **Concurrency:** single-transaction commit/rollback + deterministic
  ordering + `SELECT … FOR UPDATE` attempt (`_try_for_update`, SQLite
  fallback; real exclusion on PG/MySQL).
- **Schema:** `ix_queue_salon`, `ix_queue_barber`, `ix_queue_position`,
  `ix_queue_status`, `ix_queue_status_position`, unique
  `ix_queue_appointment_id` — all verified in the migrated schema
  (`alembic check` clean; no new migration). Seed's `waiting`
  `queue_position=1` demo row verified intact.

## 13. Realtime queue WebSocket (Phase 5A — implemented, read-only push)

Endpoint: `WS /api/v1/ws/queue/{salon_id}?token=<JWT>&barber_id=<int>&date=YYYY-MM-DD`
(`app/api/v1/queue_ws.py`; `app/ws/manager.py` + `app/ws/events.py`;
publisher `app/services/queue_events.py`). Normative detail:
`docs/backend.md` §12. **REST remains the mutation path** — client WS
messages are ignored; mutations happen via REST and are pushed post-commit
(exactly one event per success; failures emit nothing).

- **Query auth + close codes:** same JWT via `?token=` (`decode_access_token`
  only). `4401` missing/invalid/expired/unknown-user; `4400` bad `date`;
  `4404` unknown salon; `4403` RBAC (cross-barber, missing barber profile,
  unknown role). Short non-leaky reasons, no tracebacks.
- **RBAC scoping:** customer = own-scope snapshot only (`has_queue/.../
  serving summary`, foreign salon returns empty scope, no leaks); barber =
  own `barber_id` only (default own); staff/receptionist/admin = full salon
  scope (`entries[] + serving summary + scope`). Channel =
  `(salon_id, barber_id, date)`.
- **Events/payloads (no PII):** envelope `{"event", "data"}` —
  `queue.updated` (initial snapshot + fallback), `queue.created`,
  `queue.serving`, `queue.completed`, `queue.skipped`, `queue.cancelled`,
  `queue.position_changed`. Allowlist only (ids, positions, statuses,
  waits, scope, entries); publisher forwards committed
  `queue_position`/`estimated_wait_minutes` verbatim. Never:
  password/hash, JWT/secrets, phone/email/names.
- **Lifecycle/reconnect:** connect → auth → authorize → snapshot → push-wait
  (protocol auto-pong heartbeat) → disconnect cleanup (reconnect = fresh
  connect with backoff; no replay). Dead sockets pruned; broadcasts never
  raise.
- **Single-instance + Redis future:** process-local `manager` singleton —
  multi-worker/replica fan-out is not cross-process today; future Redis
  pub/sub behind `broadcast_*` without changing call sites.

## 14. Notifications (Phase 5B — implemented)

Fan-out in `app/notifications/` (service, providers, templates, prefs,
durable model); contract in `app/api/v1/notifications.py` (history GET
only); wiring in `app/main.py` lifespan. Normative detail:
`docs/backend.md` §13. Summary:

- **Architecture (post-commit consumer, no second bus):** `service.handle()`
  subscribes to `queue_events` (same feed as WS). `publish_*` runs only
  after `db.commit()` — failed transactions emit nothing. Notification
  failure never rolls back the queue: `handle()` never raises, never
  mutates queue/appointment rows; failures land as `FAILED`, REST stands.
- **Providers (mock default, real disabled without creds):**
  `send() -> Result`, `get_provider()` returns Mock while
  `{CH}_ENABLED=false` (shipped default: all `false`; record + success,
  never network) and the real stub only when `{CH}_ENABLED=true` plus
  `{CH}_HOST/USER/PASS` exist (else `Result(success=False)`). Secrets never
  logged. **Real-provider limits: mock validated only** — no live gateway
  delivery verified.
- **Types/channels:** channels `email`/`push`/`sms`; types
  `appointment_booked`, `appointment_cancelled`, `queue_joined`,
  `queue_approaching`, `turn_now`, `appointment_completed`; templates render
  `{first_name}`/`{position}`/`{wait_minutes}` only.
- **Triggers mapping:** `queue.created → queue_joined`,
  `queue.serving → turn_now` (security bypass), `queue.completed →
  appointment_completed`, `queue.cancelled → appointment_cancelled`,
  `queue.updated` (pos `<= APPROACHING_THRESHOLD`, default `2`) →
  `queue_approaching` (else silent), `queue.skipped` silent.
- **Idempotency key:** `"<type>:<appointment_id>:<channel>"` (or
  `event:<event_id>`) via `build_idempotency_key`; in-process `_SEEN_KEYS` +
  DB `UNIQUE uq_notifications_idempotency_key` (duplicate → already-queued).
- **Bounded retry max 3:** `MAX_ATTEMPTS = 3`, inline attempts per channel,
  no worker/sleep; `can_retry = attempts < 3`.
- **Persistence table + statuses:** `notifications` (`notification_id`,
  `user_id`/`appointment_id`/`queue_id` SET NULL, `channel`, `type`,
  `status PENDING/SENT/FAILED`, `template_ref`, `attempts`, `error ≤ 500`,
  `idempotency_key` unique, `created_at`, `sent_at`); outbox-only fallback.
- **Prefs defaults:** email ON, push ON, sms OFF; `turn_now` bypasses prefs.
- **Privacy:** no PII beyond first name + position + wait; bodies/logs never
  carry password/hash, JWT/secrets, phone/email content, or credentials.
- **History GET RBAC (no send endpoint):** `GET /api/v1/notifications`
  only — no POST/send. `admin` all, `customer` own-only (`200` isolated),
  `barber`/`staff` `403`, unauth `401`; `?limit=` (≤ 200) / `?offset=`.
- **WS vs notification split:** WS = ephemeral salon/barber/date channel
  snapshots; notifications = durable per-user records + history GET. Same
  post-commit feed, no independent wait calc.
- **Phase 5C boundary (no analytics):** SAWTE estimation only (see §15) — deterministic history-based, never ML; no demand
  analytics or BI dashboards.

## 15. SAWTE estimation (Phase 5C — implemented, deterministic, not ML)

SmartQueue Wait Time Estimator (`app/services/sawte.py` via
`queue_service.estimate_for_entry` / `recompute_estimates_for_scope`).
Deterministic history-based algorithmic/adaptive/historical moving-average
estimation — pure arithmetic, **not** ML (no models, training, learned
weights, or inference endpoints). Normative detail: `docs/backend.md` §14.

- **Formula:** `estimate(requester) = serving_remaining +
  SUM(expected(ahead waiting))`. `expected` = latest ≤ 5 completed
  `actual_duration_minutes` average for the same barber+service (newest by
  `appointment_id DESC`), else mandatory `Service.duration_minutes`
  fallback (missing → `0`). `serving_remaining = max(0,
  ceil(expected − elapsed))` where `elapsed = now − latest history
  `changed_at` (`in_progress`); no stamp → `ceil(expected)`. Ahead =
  same barber+date, `waiting`, lower `queue_position`. All `ceil`ed;
  measured durations use `max(1, ceil(delta))`.
- **Column + migration:** `appointments.actual_duration_minutes`
  (nullable `Integer`, `NULL` = unknown, written once on complete in the
  same `_commit_transition` transaction via `compute_actual_minutes`);
  migration `c9d1e2f3a4b5_add_actual_duration_minutes.py` (SQLite-safe
  `batch_alter_table`; downgrade drops the column).
- **Confidence `LOW`/`MEDIUM`/`HIGH` = data availability, not
  probability:** per-component `total_count` bands (0–2 / 3–5 / 6+),
  request = weakest; zero components → `LOW`. Transient, verbatim, never
  persisted.
- **API (back-compat):** `GET /queue/my-position` adds `confidence`
  alongside `estimated_wait_minutes` (old clients ignore it);
  `QueueResponse` / `MyPositionResponse` carry optional `confidence`.
- **WS:** `confidence` allowlisted in `app/ws/events.py`, forwarded
  verbatim; publisher performs no independent calculation.
- **Recalc triggers:** `recompute_estimates_for_scope(date, barber)` on
  join/serve/serve-next/complete/skip/PUT/cancel via the existing
  post-commit `queue_events` bus (no second bus; failures emit nothing,
  estimate errors never break REST).
- **Limitations:** new combos fall back with `LOW`; delays/breaks not
  modeled; confidence is history depth, not certainty; the estimate is not
  a guarantee.

Frontend untouched: no frontend file was modified for Phase 5C.
