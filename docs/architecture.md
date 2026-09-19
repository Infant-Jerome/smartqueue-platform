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
        │  WS   /api/v1/ws/queue/{salon_id}?token=&barber_id=&date= (Phase 5A, read-only push)
        ▼
   FastAPI app (app.main:app)
        │
        ├─ CORS middleware
        ├─ routers: /auth /services /barbers /appointments /queue /availability + WS /ws/queue/{salon_id}
        │
        ├─ Pydantic schemas   (request/response validation)
        ├─ Security layer     (JWT + bcrypt, api/deps.py; WS ?token= JWT, see Phase 5A)
        ├─ WS layer           (app/ws/manager.py single-instance fan-out, app/ws/events.py envelopes; publisher app/services/queue_events.py post-commit)
        ├─ Notifications      (Phase 5B: app/notifications/service.py post-commit consumer of queue_events — no second bus; providers mock-default, history GET only)
        ▼
   SQLAlchemy ORM  →  Database (SQLite / MySQL / Postgres)
```

## Component breakdown

### Backend layers

| Layer | Location | Responsibility |
| --- | --- | --- |
| API routes | `app/api/v1/` | HTTP endpoints, status codes, authorization wiring (`queue_ws.py` owns `WS /ws/queue/{salon_id}`) |
| Dependencies | `app/api/deps.py` | Current-user resolution and role guards (REST; WS reuses JWT via `?token=`) |
| WS | `app/ws/` + `app/services/queue_events.py` | `manager.py` process-local fan-out (single-instance), `events.py` `{event,data}` envelopes + allowlist sanitizer, `schemas.py` wire validation; publisher forwards committed positions/waits post-commit only |
| Notifications (5B) | `app/notifications/` + `app/api/v1/notifications.py` | `service.py` post-commit consumer of `queue_events` (no second bus; queue never rolls back on notif failure), providers (mock default, real disabled without creds), templates, prefs, durable `notifications` table; history GET only |
| Core | `app/core/` | Settings (`DATABASE_URL` override, comma-separated `CORS_ORIGINS`, JWT), engine/session, password hashing & JWT, envelope helpers |
| Models | `app/models/` (per-entity modules, re-exported via `app.models`) | `User`, `Salon`, `Barber`, `Service`, `BarberAvailability`, `Appointment`, `Queue`, `AppointmentStatusHistory` — canonical 8 tables (PK/FK list in “Canonical data model” below) |
| Schemas | `app/schemas/schemas.py` | Pydantic request/response models |
| Entrypoint | `app/main.py` | App factory, CORS, router registration, lifespan startup (`create_all`), `/api/health` envelope + `SELECT 1` DB probe |

### Frontend structure

| Path | Responsibility |
| --- | --- |
| `services/api.js` | Axios instance with JWT injection and 401 redirect; base URL from `VITE_API_BASE_URL` (fallback `/api/v1`) |
| `context/AuthContext.jsx` | Auth state + login/register/logout |
| `components/ProtectedRoute.jsx` | Route guard by auth + role |
| `pages/` | Login, Register, Dashboard, Services, Barbers, Book, Queue, Admin |

## Key design decisions

1. **JWT auth with role claims.** Tokens embed `sub` (user id) and `role`, signed `HS256` with `JWT_SECRET_KEY` and an `exp` claim from `JWT_EXPIRE_MINUTES` (default 60). Role checks are enforced in `require_role(...)` rather than only in the UI, so the API is the source of truth. Registration always creates `role="customer"` (no self-assign — `UserCreate` carries no `role` field). Clients send `Authorization: Bearer <token>` (HTTPBearer in `api/deps.py`, wired into Swagger UI); canonical roles are `customer`/`barber`/`admin`/`staff`, where `staff` is the receptionist/front-desk role.
2. **Overlap prevention (Phase 3).** The booking path enforces half-open range
   overlap (`start_a < end_b and end_a > start_b`, so back-to-back slots are
   legal) per barber+date and per customer+date, ignoring `cancelled`/`no_show`
   rows — no slot `UNIQUE`, since a plain constraint cannot express ranges.
   Conflicts return `409` (barber-taken vs own-overlap messages). The canonical
   schema models the slot as a range (`appointment_date` + `start_time`/`end_time`
   with `start_time < end_time`); the per-day lookup is indexed
   (`ix_appointment_barber_date`). Full rules: `docs/backend.md` §10.
3. **Server-derived slots (Phase 3).** `end_time = start_time +
   service.duration_minutes` — clients send no `end_time`/`customer_id`
   (`422` if smuggled). Salon hours and `barber_availability` windows are
   enforced (`400`); reschedule re-derives and re-checks.
3. **Queue as a derived entity (Phase 4 + 5A guards + 5C SAWTE).** Each appointment creates one `Queue` row (`waiting`, `salon_id` nullable SET NULL, `barber_id` not null CASCADE, `appointment_id` unique CASCADE). Queue positions are 1-based max+1 per (date[, barber]) (`ck_queue_position_positive`, never reused); wait estimates are Phase 5C SAWTE per (date, barber) scope — deterministic history-based algorithmic/adaptive/historical moving-average estimation (`estimate = serving_remaining + sum(ahead)`, latest-5 window else `Service.duration_minutes` fallback, `LOW`/`MEDIUM`/`HIGH` data-availability confidence; never ML — see Phase 5C). Appointment `in_progress` ↔ queue `serving`; `cancelled`/`no_show` mirror verbatim. `POST /queue/serve-next` + one-active-per-barber guard (`409`) + history on every queue op are landed; active list is `waiting`/`serving` ordered by `queue_position ASC`. Read-only WS push mirrors the same rows (§Phase 5A). Full rules: `docs/backend.md` §11 + §14.
4. **SQLite by default, MySQL optional, `DATABASE_URL` for production.** `DATABASE_URL` takes precedence (e.g. Render Postgres via `psycopg2-binary`); otherwise `DATABASE_TYPE` switches the engine. Baseline schema is captured in Alembic (baseline `*_initial_schema.py` + salons update `*_phase_1_model_updates.py`); startup also runs `create_all` via the lifespan handler.
5. **CORS allows the Vite dev origin.** `CORS_ORIGINS` is a comma-separated string. In production, set it to the real frontend domain (Vercel URL).

## Canonical data model (Phase 1.1)

8 tables. Canonical entity class is `Queue` (table `queue`) — never `QueueEntry`.
No `appointments.id` / `queue.id` claims: the PKs are `appointment_id` / `queue_id`.

| Table | PK | Key FKs |
| --- | --- | --- |
| `users` | `user_id` | — |
| `salons` | `salon_id` | — |
| `barbers` | `barber_id` | `user_id` → `users.user_id` (SET NULL), `salon_id` → `salons.salon_id` (SET NULL) |
| `services` | `service_id` | `salon_id` → `salons.salon_id` (SET NULL) |
| `barber_availability` | `availability_id` | `barber_id` → `barbers.barber_id` (CASCADE) |
| `appointments` | `appointment_id` | `customer_id` → `users.user_id` (CASCADE), `salon_id` → `salons.salon_id` (SET NULL, nullable), `barber_id` → `barbers.barber_id` (CASCADE), `service_id` → `services.service_id` (CASCADE) |
| `queue` | `queue_id` | `appointment_id` → `appointments.appointment_id` (CASCADE, unique — one row per appointment), `salon_id` → `salons.salon_id` (SET NULL, nullable), `barber_id` → `barbers.barber_id` (CASCADE) |
| `appointment_status_history` | `history_id` | `appointment_id` → `appointments.appointment_id` (CASCADE) |

Notes: `appointments` carries the slot as `appointment_date` + `start_time`/`end_time` (no single `appointment_time`, no per-appointment `queue_number` — position lives on `queue.queue_position`; `end_time` is server-derived). `appointment_status_history` is append-only (`old_status` nullable, `new_status`, `changed_at`) with ORM cascade wiring, written on create and every transition. `barber_availability` carries the composite index `ix_availability_barber_date`, full CRUD at `/api/v1/availability`, and booking validates against its windows when rows exist. Full column detail: `docs/backend.md` §7 and `backend/README.md` §8; booking rules: `docs/backend.md` §10.

## Phase 3 — Booking & availability (implemented)

Booking engine in `app/services/appointments_service.py`; HTTP contract in
`app/api/v1/appointments.py` (reschedule, barber scoping, on-behalf booking,
cancel-via-DELETE); queue derivation in `app/services/queue_service.py`.
Normative detail: `docs/backend.md` §10.

- **Availability endpoints: implemented.** CRUD at `/api/v1/availability`
  (`app/api/v1/availability.py` + `availability_service.py` +
  `schemas/availability.py`): reads any authenticated (optional
  `barber_id`/`date` filters); writes admin / staff / owner-barber (`403`
  otherwise); delete is hard-delete for admin/owner, deactivate
  (`status='unavailable'`) for staff. Windows are single-day
  (`422` midnight-crossing), status-whitelisted, salon-hours-checked (`422`),
  and overlap-checked (`409`). Booking validates against them when rows exist.
- **Booking flow:** `POST /api/v1/appointments` takes `{barber_id,
  service_id, appointment_date, start_time, salon_id?, booking_type?}` (`422`
  for smuggled `end_time`/`customer_id`) → salon/barber/service checks
  (`404`/`400`) → past-date and same-day past-time guards (`400`) →
  server-derived `end_time` → `booking_type` whitelist (`422`) →
  salon-hours and availability-window checks (`400`) → barber-level +
  customer-level half-open overlap checks (`409`, ignoring
  `cancelled`/`no_show`) → transactional appointment + `waiting` queue row +
  `None → booked` history row → `201`. Staff/admin may book on behalf via
  `?customer_id=` (customers: `403`).
- **Reschedule/status/cancel:** `PUT` with `appointment_date?`/`start_time?`
  re-derives `end_time` and re-checks (self excluded); terminal rows immutable
  (`400`); transition map enforced with history on every change; `DELETE` is
  cancel (idempotent `200`, `400` when completed), not hard delete.

## Phase 4 — Queue engine (implemented, Phase 5A guards landed)

Engine in `app/services/queue_service.py`; contract in
`app/api/v1/queue.py`; appointment-side sync in
`app/services/appointments_service.py` + `app/api/v1/appointments.py`.
Normative detail: `docs/backend.md` §11.

- **Lifecycle:** `waiting → serving/no_show/cancelled`, `serving →
  completed/cancelled` on the queue (appointment `waiting → in_progress →
  completed`; `cancelled`/`no_show` are terminal branches). `waiting →
  completed` directly is `400`; terminal-out is `409`; unknown `PUT`
  status is `422`. Endpoints: `POST /serve-next`, `POST /{id}/serve|
  complete|skip`, `PUT /{id}`, `GET /` (scope filters), `GET /current`
  (`200` + `null` when empty), `GET /my-position`.
- **Position/scoping:** 1-based max+1 per (date[, barber]), never reused;
  `appointment_id` unique CASCADE, `salon_id` nullable SET NULL,
  `barber_id` not null CASCADE. No renumbering/compaction.
- **Serve-next + one-active (landed):** `POST /queue/serve-next`
  (`{barber_id*, salon_id?}`) serves the smallest `waiting` position for
  (today, barber[+ salon]); `404` when empty; **`409` one-active guard**
  when a `serving` row is already active for the (date, barber) scope
  (also enforced in `serve` / `_commit_transition`).
- **Wait:** deterministic DB-duration sum per (date, barber) scope
  (`serving remainder + sum ahead`, missing → 0), recomputed on every
  mutation; no ML. **Sync/history (landed):** every queue op goes through
  `_commit_transition` (queue + appointment + history + estimates, one
  commit) — serve/complete/skip/PUT all write `AppointmentStatusHistory`.
- **RBAC/errors/concurrency:** operate = non-customer + barber own-scope
  (`403` otherwise), `my-position` = any authenticated; `404` unknown /
  empty scope, `409` queue guards + booking overlap, `400` illegal edges,
  `422` bad bodies; single-transaction commit/rollback, deterministic
  ordering, `SELECT … FOR UPDATE` attempt with SQLite fallback.
- **Schema:** `ix_queue_salon`, `ix_queue_barber`, `ix_queue_position`,
  `ix_queue_status`, `ix_queue_status_position`, unique
  `ix_queue_appointment_id` — verified present, `alembic check` clean, no
  new migration.

## Phase 5A — Realtime queue WebSocket (implemented, read-only push)

Endpoint: `WS /api/v1/ws/queue/{salon_id}?token=<JWT>&barber_id=<int>&date=YYYY-MM-DD`
(`app/api/v1/queue_ws.py`; `app/ws/manager.py` + `app/ws/events.py`;
publisher `app/services/queue_events.py`). Normative detail:
`docs/backend.md` §12. **REST remains the mutation path** — client WS
messages are ignored; mutations happen via REST and are pushed post-commit
(exactly one event per success; failures emit nothing).

- **Query auth + close codes:** same JWT via `?token=`. `4401`
  missing/invalid/expired/unknown-user; `4400` bad `date`; `4404` unknown
  salon; `4403` RBAC (cross-barber, missing barber profile, unknown role).
- **RBAC scoping:** customer = own-scope snapshot only (foreign salon
  returns empty scope, no leaks); barber = own `barber_id` only (default
  own); staff/receptionist/admin = full salon scope. Channel =
  `(salon_id, barber_id, date)`.
- **Events/payloads (no PII):** envelope `{"event", "data"}` —
  `queue.updated` (initial snapshot + fallback), `queue.created`,
  `queue.serving`, `queue.completed`, `queue.skipped`, `queue.cancelled`,
  `queue.position_changed`. Allowlist only (ids, positions, statuses,
  waits, scope, entries); publisher forwards committed values verbatim.
  Never: password/hash, JWT/secrets, phone/email/names.
- **Lifecycle/reconnect:** connect → auth → authorize → snapshot →
  push-wait (protocol auto-pong heartbeat) → disconnect cleanup; reconnect
  = fresh connect with backoff (no replay). Dead sockets pruned;
  broadcasts never raise.
- **Single-instance + Redis future:** process-local `manager` singleton —
  no cross-process fan-out today; future Redis pub/sub behind
  `broadcast_*` without changing call sites.

## Deliberately future — Phase 5C boundary (SAWTE landed, analytics not)

Out of scope through Phase 5C (see `problemstatement.md` §9 and `docs/backend.md` §8):
appointment engine (advanced — multi-barber availability search, recurring bookings,
deposits/holds, calendar sync), queue engine (advanced — priority/multi-branch queues),
demand analytics/BI. Notifications are landed (Phase 5B,
mock-default providers + history GET only; real gateway delivery unvalidated).
SAWTE estimation is landed (Phase 5C, deterministic history-based
algorithmic/adaptive/historical moving-average estimation — never ML; see below).
Landed scope is single-slot booking with
server-derived slots and the half-open overlap rule, reschedule with re-validation,
history on every appointment-side **and** queue-side transition, the waiting → serving → completed lifecycle with
`serve-next`, one-active-per-barber guard, per-(date, barber) positions, the SAWTE wait estimate,
and read-only WS snapshots + post-commit push (REST remains the mutation path),
plus Phase 5B post-commit notifications (same `queue_events` feed, mock-default,
history GET only, queue never rolls back on notification failure).

## Phase 5B — Notifications (implemented)

Fan-out in `app/notifications/`; HTTP contract in
`app/api/v1/notifications.py` (history GET only); wiring in `app/main.py`
lifespan (`subscribe_notifications`). Normative detail: `docs/backend.md`
§13; `backend/README.md` §14.

- **Architecture (post-commit consumer, no second bus):**
  `NotificationService.handle()` subscribes to `queue_events` — the same
  post-commit feed as WS. `publish_*` runs only after `db.commit()`; failed
  transactions emit nothing. Notification failure never rolls back the
  queue (`handle()` never raises, never mutates queue/appointment rows).
- **Providers (mock default, real disabled without creds):** Mock
  (record + success, never network) while `{CH}_ENABLED=false` (shipped
  default); real stubs (`SmtpEmailProvider`, `HttpPushProvider`,
  `HttpSmsProvider`) only when `{CH}_ENABLED=true` + host creds, else
  `Result(success=False)`. Secrets never logged. **Real-provider limits:
  mock validated only** — no live gateway delivery verified.
- **Types/channels:** `email`/`push`/`sms`; `appointment_booked`,
  `appointment_cancelled`, `queue_joined`, `queue_approaching`, `turn_now`,
  `appointment_completed`.
- **Triggers mapping:** `queue.created → queue_joined`,
  `queue.serving → turn_now` (prefs bypass), `queue.completed →
  appointment_completed`, `queue.cancelled → appointment_cancelled`,
  `queue.updated` (pos `<= APPROACHING_THRESHOLD=2`) → `queue_approaching`
  (else silent), `queue.skipped` silent.
- **Idempotency key:** `"<type>:<appointment_id>:<channel>"` (or
  `event:<event_id>`); in-process dedupe + DB `UNIQUE
  uq_notifications_idempotency_key`.
- **Bounded retry max 3:** `MAX_ATTEMPTS = 3`, inline, no worker/sleep.
- **Persistence table + statuses:** `notifications` (`PENDING`/`SENT`/
  `FAILED`, `attempts`, `error ≤ 500`, unique idempotency key); outbox-only
  fallback.
- **Prefs defaults:** email ON, push ON, sms OFF; `turn_now` bypasses prefs.
- **Privacy:** no PII beyond first name + position + wait; no
  password/hash, JWT/secrets, phone/email content, or credentials in
  bodies/logs.
- **History GET RBAC (no send endpoint):** `GET /api/v1/notifications`
  only — `admin` all, `customer` own-only, `barber`/`staff` `403`, unauth
  `401`.
- **WS vs notification split:** WS = ephemeral channel snapshots; notifications
  = durable per-user records + history GET. Same feed, no independent wait calc.
- **Phase 5C boundary (no analytics):** SAWTE estimation only (see Phase 5C
  below) — deterministic history-based, never ML; no demand
  analytics or BI dashboards.

## Phase 5C — SAWTE estimation (implemented, deterministic, not ML)

SmartQueue Wait Time Estimator (`app/services/sawte.py` via
`queue_service.estimate_for_entry` / `recompute_estimates_for_scope`). Deterministic history-based algorithmic/adaptive/historical moving-average estimation — pure arithmetic over measured durations, **not** ML (no models,
training, learned weights, or inference endpoints). Normative detail:
`docs/backend.md` §14; `backend/README.md` §15.

- **Formula:** `estimate(requester) = serving_remaining +
  SUM(expected(ahead waiting))`. `expected` = historical moving average
  (latest ≤ 5 completed `actual_duration_minutes` for the same
  barber+service, newest by `appointment_id DESC`) else mandatory
  `Service.duration_minutes` fallback (missing → `0`).
  `serving_remaining = max(0, ceil(expected − elapsed))` with `elapsed =
  now − latest history `changed_at` (`in_progress`); no stamp →
  `ceil(expected)`. Ahead = same barber+date, `waiting`, lower
  `queue_position`. All `ceil`ed; measured durations use `max(1,
  ceil(delta))`.
- **Column + migration:** `appointments.actual_duration_minutes`
  (nullable `Integer`, `NULL` = unknown, written once on complete in the
  same transaction via `compute_actual_minutes`); migration
  `c9d1e2f3a4b5_add_actual_duration_minutes.py`.
- **Confidence `LOW`/`MEDIUM`/`HIGH` = data availability, not
  probability:** per-component `total_count` bands (0–2 / 3–5 / 6+),
  request = weakest; zero components → `LOW`. Transient, verbatim, never
  persisted.
- **API (back-compat):** `GET /queue/my-position` adds `confidence`
  alongside `estimated_wait_minutes`; `QueueResponse` carries optional
  `confidence`.
- **WS:** `confidence` allowlisted in `app/ws/events.py`, forwarded
  verbatim; no independent calculation.
- **Recalc triggers:** `recompute_estimates_for_scope(date, barber)` on
  join/serve/serve-next/complete/skip/PUT/cancel via the existing
  post-commit `queue_events` bus (no second bus; failures emit nothing).
- **Limitations:** new combos fall back with `LOW`; delays/breaks not
  modeled; confidence is history depth, not certainty; the estimate is not
  a guarantee.

Frontend untouched: Phase 5C modifies backend estimation, REST, and WS
payloads only — no frontend file was changed.

## Security

- Passwords hashed with bcrypt.
- JWT signed with `JWT_SECRET_KEY` (HS256); extend expiry via `JWT_EXPIRE_MINUTES`.
- Auth endpoints (`/api/v1/auth`): `POST /register` → `201` (always `customer`, `400` duplicate, `422` invalid body); `POST /login` → `200` (`401` bad credentials); `GET /me` → `200` (`401` missing/invalid/expired token). All in the uniform `{success, data, message}` envelope.
- Endpoint authorization layered by role (`401` unauthenticated, `403` forbidden): services/barbers reads are public, writes admin-only; appointments require auth (customers own-only incl. cancel-only PUT, barbers assigned-only, staff/admin all; `DELETE` is cancel, not hard delete); availability reads any-authenticated, writes admin/staff/owner-barber; queue operate (`GET /queue`, `GET /current`, serve/serve-next/skip/PUT) is non-customer + barber own-scope, `my-position` is any authenticated user; WS `/ws/queue/{salon_id}?token=` enforces the same RBAC per channel (`4401` auth, `4403` forbidden, `4400` bad date, `4404` unknown salon) with allowlisted no-PII payloads. Full matrix: `docs/backend.md` §9 + §12.
- In production: rotate `JWT_SECRET_KEY`, set `DEBUG=False`, and use MySQL over SQLite.
- Scope: auth covers identity + role guards only (REST `Bearer`, WS `?token=`); advanced appointment engines are still Phase 5 future; queue realtime is read-only push (Phase 5A).

## Testing strategy

Phase 8 added a pytest suite (`backend/tests/`):

- **Unit** — password hashing & JWT round-trips, queue-number assignment.
- **Integration/API** — TestClient fixture over an isolated temp SQLite DB covering auth, services, barbers, appointments (including double-booking conflict), and queue lifecycle (serve → complete).

See [Rubber-stamp check](../backend/tests/README.md) for how to run them.

## Contributing workflow

1. Add/change a model → write an Alembic revision (baseline `initial schema` already exists; verify with `alembic upgrade head` on a fresh DB).
2. Update the Pydantic schema if the API contract changes.
3. Add/adjust a route in `app/api/v1/`.
4. Add a test in `backend/tests/`; run `pytest -v`.
5. Update the CHANGELOG.

## Deployment

- Backend → Render (`render.yaml`): `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`, health check `/api/health` (envelope + DB probe).
- Frontend → Vercel (`frontend/vercel.json`): Vite build to `dist`, `VITE_API_BASE_URL` points at the Render `/api/v1`.
- CI: `backend.yml` (pytest + Alembic upgrade cycle), `frontend.yml` (lint + build).