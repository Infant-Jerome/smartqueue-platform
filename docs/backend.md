# Backend Guide — SmartQueue Phases 1–5C

Docs-only companion to `backend/README.md` (single source of truth for
backend detail; the root `README.md` keeps only the quick-start summary).
Describes the **implemented** Phases 1–4 backend (auth in §9, booking rules
in §10, queue engine in §11) plus Phase 5A read-only realtime in §12
(WS snapshots + server-push; REST remains the mutation path) plus Phase 5B
notifications in §13 (post-commit consumer of `queue_events`; history GET
only) plus Phase 5C SAWTE in §14 (deterministic history-based
algorithmic/adaptive/historical moving-average estimation — not ML).
Future-phase items are listed in §8 and are **not** implemented — do not present them
as available.

## 1. Backend architecture

```text
React Frontend (Vite, :5173, proxies /api → :8000)
        │  REST JSON  /api/v1/*  +  WS /api/v1/ws/queue/{salon_id} (Phase 5A, read-only push)
        ▼
FastAPI (app.main:app, :8000)
        ├─ CORS middleware            ← CORS_ORIGINS (comma-separated)
        ├─ routers  app/api/v1/       ← auth, services, barbers, appointments, queue, availability, queue_ws
        ├─ deps     app/api/deps.py   ← current user + require_role(...) guards (REST); WS uses ?token= JWT (see §12)
        ├─ services app/services/     ← appointments_service, queue_service, queue_events (post-commit publisher)
        ├─ notifs   app/notifications/  ← service (post-commit consumer of queue_events), providers, templates, prefs (Phase 5B, §13)
        ├─ ws       app/ws/           ← manager (single-instance fan-out), events (envelopes + sanitizer), schemas
        ├─ schemas  app/schemas/      ← Pydantic v2 validation
        ├─ core     app/core/         ← config, database, security, response envelope
        ▼
SQLAlchemy 2.0 ORM (app/models/*.py) → SQLite | MySQL (PyMySQL) | Postgres (psycopg2)
```

Request path: router (thin: status codes + auth wiring) → service (business
rules) → ORM session (`get_db`) → DB. All responses use the uniform envelope
`{success, data, message}` (`app/core/response.py`), including error handlers
and `GET /api/health` in `app/main.py`. Lifespan startup runs
`Base.metadata.create_all`; JWT (`sub` + `role`, HS256, bcrypt hashes) is
enforced server-side so the API — not the UI — is the source of truth.

## 2. Environment variables

Loaded from `backend/.env` (template: `backend/.env.example`, mirrored at
root `.env.example`). `DATABASE_URL` wins when set; otherwise the
`DATABASE_TYPE`-based fallback applies. Only `JWT_SECRET_KEY` is required.
No real secrets are stored in the repo — use placeholder values in docs.

| Variable | Description | Required |
| --- | --- | --- |
| `DATABASE_URL` | Full URL override, e.g. `postgresql+psycopg2://USER:PASSWORD@HOST:5432/DB` (Render). Takes precedence | N |
| `DATABASE_TYPE` | `sqlite` (default) or `mysql` — used only when `DATABASE_URL` is empty | N |
| `DATABASE_HOST` / `DATABASE_PORT` / `DATABASE_USER` / `DATABASE_PASSWORD` / `DATABASE_NAME` | Field-based config (MySQL path) | N |
| `JWT_SECRET_KEY` | Signing secret — **rotate in production**, never commit | Y |
| `JWT_ALGORITHM` | Default `HS256` | N |
| `JWT_EXPIRE_MINUTES` | Token lifetime | N |
| `APP_NAME` / `APP_VERSION` | Display name / version (surfaced in `/api/health` and `/docs`) | N |
| `DEBUG` | `true`/`false` (also toggles SQL echo) — set `False` in production | N |
| `CORS_ORIGINS` | Comma-separated origins, e.g. `http://localhost:5173,http://localhost:3000`; production = real frontend domain | N |
| `NOTIFS_ENABLED` | Master switch for Phase 5B fan-out (default `True`) | N |
| `APPROACHING_THRESHOLD` | `queue.updated` notifies as `queue_approaching` only when `queue_position <= threshold` (default `2`) | N |
| `EMAIL_ENABLED` / `PUSH_ENABLED` / `SMS_ENABLED` | Channel real-provider gates — all default `false` (mock path); real stubs stay disabled without creds (see §13) | N |
| `EMAIL_HOST/PORT/USER/PASS/FROM`, `PUSH_*`, `SMS_*` | Real-provider placeholders only — empty by default, never real secrets (see §13) | N |

## 3. Database setup

- **Dev (default): SQLite.** `DATABASE_TYPE=sqlite`, `DATABASE_URL` empty →
  file `backend/smartqueue.db`. Auto-created on startup; seed with `python seed.py`.
- **Prod option A: MySQL.** `DATABASE_TYPE=mysql` + host/port/user/password/name
  (`mysql+pymysql://...` via the `pymysql` driver).
- **Prod option B: Postgres (e.g. Render).** Full `DATABASE_URL`
  (`postgresql+psycopg2://...` via `psycopg2-binary`); takes precedence over
  field-based settings. Start command applies migrations first
  (`alembic upgrade head && uvicorn ...`, see `render.yaml`).
- **Tests: isolated SQLite.** `tests/conftest.py` builds a per-test in-memory
  SQLite DB (`sqlite://` + `StaticPool`) and overrides `get_db` — no local DB
  state or setup required; `smartqueue.db` is never touched.

## 4. Migration commands

Revisions: `ebc12f99c799_initial_schema.py` (initial baseline) →
`f7ad2ddb6a36_add_salons_and_phase_1_model_updates.py` (adds `salons` plus
salon/user links on barbers/services) →
`eb348e90a283_canonicalize_pks_retire_legacy.py` (canonical PK/FK names,
retires legacy columns, creates `barber_availability` +
`appointment_status_history`, explicit `ix_*` indexes including
`ix_appointment_barber_date` and `ix_availability_barber_date`). The canonical
8-table schema is defined in `app/models/*.py` (see §7);
`app/models/models.py` is now a deprecated re-export shim that defines no
tables (`QueueEntry = Queue` alias only). Verified on a fresh SQLite DB:
`upgrade head` → `alembic check` clean (no drift) → `downgrade -1` →
`upgrade head` → `check` clean — no further migration needed. Both booking
indexes (`appointments(barber_id, appointment_date)`,
`barber_availability(barber_id, date)`) exist in the models and in the
migrated schema.

```bash
cd backend
alembic upgrade head                                  # apply all (incl. baseline)
alembic revision --autogenerate -m "describe change" # new revision after model edits
alembic upgrade head                                  # apply it
alembic downgrade -1                                  # roll back one revision
alembic history                                       # list revisions
alembic current                                       # show current revision
```

CI (`.github/workflows/backend.yml`) runs pytest plus a fresh-SQLite
`upgrade/downgrade/upgrade` cycle, so keep migrations reversible.

## 5. Local run

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate   |  Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # set JWT_SECRET_KEY
python seed.py              # demo data (admin + customer, 3 barbers, 5 services)
uvicorn app.main:app --reload --port 8000
```

API: `http://localhost:8000/api/v1` · Health: `http://localhost:8000/api/health`.

## 6. Testing

```bash
cd backend
pytest -v                   # or: python -m pytest -v
```

`pytest.ini` sets `testpaths = tests`. Fixtures (in-memory SQLite engine,
scoped session, `TestClient` with `get_db` overridden, admin/customer users +
bearer headers, barber+service seed) live in `tests/conftest.py`. Suites:
`test_auth`, `test_services`, `test_barbers`, `test_appointments`
(incl. double-booking 409), `test_queue` (serve → complete). Full matrix:
`backend/tests/README.md`.

## 7. Swagger / ReDoc + model overview

- **Interactive docs** (auto-generated, no extra setup):
  Swagger UI `http://localhost:8000/docs`, ReDoc `http://localhost:8000/redoc`,
  OpenAPI JSON `http://localhost:8000/openapi.json`.
- **Model overview — 8 canonical entities** (`app/models/*.py`, re-exported
  via `app.models`; authoritative over any conflicting count). Canonical entity
  class is `Queue` (table `queue`) — never `QueueEntry`. No `appointments.id`
  / `queue.id` claims: PKs are `appointment_id` / `queue_id`.
  - `User` (`users`, PK `user_id`) — `name`, `email` (unique + indexed),
    `phone`, `password_hash` (bcrypt), `role` (`customer`/`barber`/`admin`/`staff`);
    1:N → appointments (via `customer_id`); 1:1 → barber profile.
  - `Salon` (`salons`, PK `salon_id`) — `name`/`address`/`phone`,
    `opening_time`/`closing_time` (seeded 09:00–18:00; booking must fit inside
    them — `400` otherwise — see §10), `status`; 1:N → barbers, services,
    appointments, queue entries (no delete cascades — deleting a salon must
    not wipe history).
  - `Barber` (`barbers`, PK `barber_id`) — `user_id` → `users.user_id`
    (SET NULL, nullable), `salon_id` → `salons.salon_id` (SET NULL, nullable);
    `name`/`specialization`/`phone`, `experience_years` (≥ 0),
    `availability_status`; 1:N → appointments, availability windows, queue entries
    (no delete cascade on appointments — history survives).
  - `Service` (`services`, PK `service_id`) — `salon_id` →
    `salons.salon_id` (SET NULL, nullable); `service_name`, `description`,
    `duration_minutes` (> 0), `price` (≥ 0), `status`; 1:N → appointments
    (no delete cascade — history survives).
  - `BarberAvailability` (`barber_availability`, PK `availability_id`) —
    `barber_id` → `barbers.barber_id` (CASCADE); `date`, `start_time`/`end_time`
    (`start_time < end_time`), `status`; composite index
    `ix_availability_barber_date` (`barber_id`, `date`). Full CRUD at
    `/api/v1/availability` (admin / staff / owner-barber writes, see §10);
    booking validates requested slots against these windows when rows exist
    for the barber+date.
  - `Appointment` (`appointments`, PK `appointment_id`) — `customer_id` →
    `users.user_id` (CASCADE), `salon_id` → `salons.salon_id` (SET NULL,
    nullable — single-salon v1), `barber_id` → `barbers.barber_id` (CASCADE),
    `service_id` → `services.service_id` (CASCADE); slot as `appointment_date`
    + `start_time`/`end_time` (`start_time < end_time`); `status` (default
    `booked`), `booking_type` (default `online`); `actual_duration_minutes`
    (nullable `Integer`, Phase 5C SAWTE measured service time — `NULL` =
    unknown, populated once on complete via
    `services.sawte.compute_actual_minutes`, see §14); indexes on customer, salon,
    barber, service, (`barber_id`, `appointment_date`), `status`. 1:0..1 →
    `Queue` (delete-orphan); 1:N → status history (delete-orphan). No slot
    `UNIQUE`: range-overlap prevention is enforced in
    `appointments_service.create_appointment` (half-open `[start, end)`,
    ignoring `cancelled`/`no_show` rows — see §10), not by a plain constraint.
  - `Queue` (`queue`, PK `queue_id`) — `appointment_id` →
    `appointments.appointment_id` (CASCADE, unique — one row per appointment),
    `salon_id` → `salons.salon_id` (SET NULL, nullable), `barber_id` →
    `barbers.barber_id` (CASCADE, not null); `queue_position` (1-based, ≥ 1,
    per-day max+1 — see §11), `joined_at`, `estimated_wait_minutes`
    (nullable — `service.duration_minutes` at booking), `status` (default
    `waiting`; live values `waiting`/`serving`/`completed`, plus mirrored
    `cancelled`/`no_show` via appointment sync — see §11);
    indexes on salon (`ix_queue_salon`), barber (`ix_queue_barber`),
    position (`ix_queue_position`), status (`ix_queue_status`),
    (`status`, `queue_position`) (`ix_queue_status_position`), and unique
    `appointment_id` (`ix_queue_appointment_id`). All verified present in
    the migrated schema (temp-DB inspect 2026-09-18; `alembic check` clean,
    downgrade/upgrade cycle clean — no new migration).
  - `AppointmentStatusHistory` (`appointment_status_history`, PK `history_id`) —
    `appointment_id` → `appointments.appointment_id` (CASCADE); `old_status`
    (nullable — creation row has no previous status), `new_status`,
    `changed_at` (indexed); append-only, written on create (`None → booked`)
    and on every status transition/cancel (see §10).
- Booking flow: `POST /api/v1/appointments` takes
  `{barber_id, service_id, appointment_date, start_time, salon_id?,
  booking_type?}` — `end_time`/`customer_id` are rejected (`422`,
  `extra="forbid"`); the server derives `end_time = start_time +
  service.duration_minutes`. Validates salon/barber/service (`404` unknown,
  `400` inactive or cross-salon mismatch), past dates and same-day past times
  (`400`), salon hours and availability windows (`400`), then rejects
  overlapping slots with `409` (see §10). On success assigns the next per-day
  queue position, inserts the `waiting` queue row (`estimated_wait_minutes`
  from `service.duration_minutes`) plus the `None → booked` history row, and
  returns `201` with embedded `queue_position`. Queue flow: staff `serve` →
  `complete`, linked appointment status updated consistently;
  `GET /queue/my-position` reports people-ahead and estimated wait
  (`people-ahead × service-duration`).
- Transitional note: routes/services/schemas use the canonical names
  (`appointment_id`, `customer_id`, `queue_position`,
  `estimated_wait_minutes`, `Queue`); `QueueEntry` survives only as a
  deprecated alias in the `app/models/models.py` shim. Old test payloads that
  still send `end_time`/`appointment_time` now get `422` (`extra="forbid"`).

## 8. Deliberately FUTURE phase — Phase 5C boundary (SAWTE landed, analytics not)

Do **not** claim these; no code, config, or endpoints for them exist through
Phase 5C except SAWTE in §14 (see `problemstatement.md` §9 Out of Scope). Phases 3–4 implement the
booking rules in §10 and the queue engine in §11; Phase 5A adds read-only
realtime in §12 (WS snapshots + server-push; REST remains the mutation path);
Phase 5B adds notifications in §13 (post-commit consumer, mock providers by
default, history GET only); Phase 5C adds SAWTE estimation in §14
(deterministic history-based only, never ML). Everything below stays out:

1. **Appointment engine (advanced)** — multi-barber availability search,
   recurring bookings, deposits/holds, calendar sync. Implemented today:
   single-slot booking with server-derived slots (§10 overlap rule),
   availability CRUD, reschedule, per-transition history.
2. **Queue engine (advanced)** — priority queues, multi-branch queues.
   Implemented today: waiting → serving → completed lifecycle with per-day
   numbers, `POST /queue/serve-next`, one-active-per-barber guard, history
   on every queue op (§11), plus read-only WS push (§12) replacing the old
   10 s polling note.
3. **Notifications (Phase 5B — implemented, see §13).** Landed scope is
   post-commit fan-out with mock-default providers, history GET only, and
   bounded retry. Still out of scope: real gateway delivery (unvalidated —
   mock validated only), user-managed preference endpoints, multi-language
   templates.
4. **SAWTE estimation (Phase 5C — implemented, see §14).** Landed scope is the deterministic history-based algorithmic/adaptive/historical moving-average estimation in `app/services/sawte.py`
    (`estimate = serving_remaining + sum(ahead)`, latest-5 window,
    `Service.duration_minutes` fallback, `LOW`/`MEDIUM`/`HIGH` data-availability
    confidence). This is **not** ML: no models, training pipelines, or
    inference endpoints exist. Still out of scope: demand analytics, BI
    dashboards.

Also out of scope: payments, ratings/reviews, multi-branch, mobile apps.

## 9. Authentication & authorization (Phase 2)

Implemented auth lives in `app/api/v1/auth.py` + `app/api/deps.py` +
`app/core/security.py`. All responses use the uniform envelope
`{success, data, message}`.

### Endpoints (all under `/api/v1/auth`)

| Method & path | Auth | Success | Errors |
| --- | --- | --- | --- |
| `POST /api/v1/auth/register` | Public (no token). Body: `name`, `email`, `password`, optional `phone` | `201` + `{access_token, token_type: "bearer", user}` | `400` email already registered; `422` validation failure |
| `POST /api/v1/auth/login` | Public (no token). Body: `email`, `password` | `200` + `{access_token, token_type: "bearer", user}` | `401` invalid email or password |
| `GET /api/v1/auth/me` | Bearer token required | `200` + current `UserResponse` | `401` missing/invalid/expired token, bad payload, or user not found |

### JWT

- Algorithm `HS256` (default `JWT_ALGORITHM`), signed with `JWT_SECRET_KEY`
  — rotate in production, never commit.
- Expiry: `exp` claim set at issue from `JWT_EXPIRE_MINUTES` (default `60`);
  expired tokens decode to `None` and are rejected with `401`.
- Claims: `sub` = `User.user_id` (string), `role` = `User.role`.
  `GET /me` and `require_role(...)` re-load the user by `sub` per request,
  so the DB — not the token alone — is the source of truth.
- Passwords are bcrypt hashes (`password_hash`); plaintext is never stored
  and `verify_password` treats malformed hashes as a non-match.

### Default role & no self-assign

- `POST /register` **always** creates `role="customer"` — the request schema
  (`UserCreate`) carries no `role` field, so callers cannot self-assign
  `admin`/`staff`/`barber`. Elevated roles are granted out-of-band
  (e.g. dev seed users below) or by a future admin-managed flow.
- Canonical roles (`UserRole`): `customer` / `barber` / `admin` / `staff`.
  "Receptionist" is the operational label for the `staff` role (front-desk
  queue operators); it is not a separate role value.

### RBAC matrix

Enforced server-side via `require_role(...)` (`401` unauthenticated,
`403` insufficient permissions). `barber` is a login-capable user role
(optionally linked 1:1 to a `Barber` profile via `Barber.user_id`); it
confers no staff powers on its own.

| Area | customer | barber | receptionist (`staff`) | admin |
| --- | --- | --- | --- | --- |
| `POST /auth/register`, `POST /auth/login` | Public | Public | Public | Public |
| `GET /auth/me` | Own profile | Own profile | Own profile | Own profile |
| `GET /services`, `GET /barbers` (list + detail) | Public | Public | Public | Public |
| `POST/PUT/DELETE /services`, `/barbers` | `403` | `403` | `403` | Allowed |
| `GET /appointments` | Own only | Assigned only | All | All |
| `GET /appointments/{id}` | Own only (`403` otherwise) | Assigned only (`403` otherwise) | Any | Any |
| `POST /appointments` (`{barber_id, service_id, appointment_date, start_time, salon_id?, booking_type?}`; `end_time`/`customer_id` in body → `422`) | Own bookings (`201`; `404` unknown barber/service/salon; `400` past slot, inactive entity, cross-salon, hours/window violation; `422` bad shape; `409` overlap; `?customer_id=` → `403`) | Same as customer | Same, plus `?customer_id=` on-behalf booking | Same, plus `?customer_id=` on-behalf booking |
| `PUT /appointments/{id}` (reschedule `appointment_date?`/`start_time?` + `status?`) | Own + cancel-only (`403` otherwise) | Assigned (status syncs derived queue row; terminal rows `400`) | Any | Any |
| `DELETE /appointments/{id}` (= cancel, not hard delete) | Own (`400` if completed) | Assigned | Allowed | Allowed |
| `GET /queue`, `PUT /queue/{id}`, `POST /queue/{id}/serve`, `POST /queue/{id}/complete` | `403` | `403` | Allowed | Allowed |
| `GET /queue/my-position` | Own position | Own position | Own position | Own position |
| `/availability` | Any authenticated read; write = admin / staff / owner-barber (`403` customer / non-owner barber); delete = admin & owner hard-delete, staff deactivates | Same | Same | Same |

### Swagger / Bearer

- `app/api/deps.py` uses `HTTPBearer`, so Swagger UI (`/docs`) shows an
  **Authorize** button: paste `<access_token>` (it sends
  `Authorization: Bearer <token>`). ReDoc (`/redoc`) and
  `/openapi.json` expose the same bearer scheme.

### Seed logins (dev only)

`python seed.py` is dev/demo only and refuses to run in production
(see `backend/seed.py` guard). It seeds four logins (emails printed,
passwords never printed; overrides via `SEED_*_EMAIL` / `SEED_*_PASSWORD`):
`admin@salon.com` (`admin`), `jerome@salon.com` (`customer`),
`arun@salon.com` (`barber`, linked to a `Barber` profile),
`reception@salon.com` (`staff` — receptionist). It also seeds the demo salon
(hours 09:00–18:00), one `barber_availability` window (first barber, today,
09:00–18:00) covering the demo appointment (10:00–10:30), its `waiting` queue
row (`queue_position=1`), and the creation history row (`None → booked`).

### Scope note

Auth covers identity + role guards only (REST via `Authorization: Bearer`,
WS via `?token=` — see §12). The advanced appointment engines
(multi-barber search, recurring bookings) are **still Phase 5 future**
(see §8). Phase 3 booking rules are in §10; the Phase 4 queue engine is
in §11; Phase 5A read-only realtime is in §12.

## 10. Booking & availability (Phase 3 — implemented)

Booking engine in `app/services/appointments_service.py`; HTTP contract in
`app/api/v1/appointments.py` (reschedule, barber scoping, on-behalf booking,
cancel-via-DELETE); queue derivation in `app/services/queue_service.py`.
All responses use the uniform envelope `{success, data, message}`.

### Availability endpoints (`/api/v1/availability` — implemented)

Routes in `app/api/v1/availability.py`, rules in
`app/services/availability_service.py`, schemas in
`app/schemas/availability.py`. All in the uniform envelope.

| Method & path | Auth | Success | Errors |
| --- | --- | --- | --- |
| `POST /api/v1/availability` (`barber_id`, `date`, `start_time`, `end_time`, `status?` default `available`) | admin, staff/receptionist, owner-barber (via `Barber.user_id`) | `201` + window | `404` unknown barber; `422` `start >= end` (midnight-crossing rejected), bad `status`, or window outside salon hours; `409` overlapping window same barber+date; `403` customer / non-owner barber |
| `GET /api/v1/availability?barber_id=&date=` | Any authenticated | `200` list (ordered by date, start) | `401` |
| `GET /api/v1/availability/{id}` | Any authenticated | `200` | `404` |
| `PUT /api/v1/availability/{id}` (partial; may move `barber_id`) | Same write rule — a barber must own both source and destination | `200` | `403`/`404`/`409`/`422` as above (self excluded from overlap) |
| `DELETE /api/v1/availability/{id}` | Admin: hard delete; owner-barber: hard delete own; staff/receptionist: deactivate (`status='unavailable'`); customer/non-owner barber → `403` | `200` | `403` / `404` |

Window rules: `status` whitelist `available`/`unavailable`/`off`
(case-insensitive, normalized); windows are single-day; a window must fit
inside the barber's salon hours (`422` when both bounds set; midnight-crossing
salon configs rejected as unsupported).

Booking interplay: when windows exist for the barber+date, the requested slot
must sit inside an `available` window and must not overlap an
`unavailable`/`off`/`blocked` window (`400`); a barber with no windows for
the date is treated as openly scheduled.

### Booking flow (`POST /api/v1/appointments` → `201`)

Request contract: `{barber_id, service_id, appointment_date, start_time,
salon_id?, booking_type?}`. `end_time`, `customer_id`/`user_id` in the body
are rejected with `422` (`extra="forbid"`); staff/admin may book on behalf of
another customer via `?customer_id=<id>` (customers using it get `403`).

1. Load barber (`404`); reject `availability_status` `inactive`/`unavailable`
   (`400`). Load service (`404`); reject inactive (`400`). Resolve salon:
   explicit `salon_id` (`404` unknown, `400` inactive) else barber's then
   service's salon; barber/service must belong to it (`400` cross-salon).
2. Date guards: past `appointment_date` → `400`; same-day `start_time`
   already past → `400`; malformed date → `422`.
3. `end_time = start_time + service.duration_minutes` (**server-derived**,
   never trusted from the client).
4. `booking_type` whitelist `online`/`walk_in` (default `online`; else `422`).
5. Salon hours: slot must fit inside resolved salon's
   `opening_time`/`closing_time` (`400`; skipped when unset/unknown).
   Availability: when windows exist for barber+date, the slot must sit inside
   an `available` window and must not overlap an `unavailable`/`off`/
   `blocked` window (`400`); no windows → openly scheduled.
6. Overlap checks (see below) → `409`.
7. Transactional create: `Appointment(status="booked")` + next per-day
   `queue_position` + `waiting` queue row (`estimated_wait_minutes` from the
   service) + history row (`None → booked`). Failures roll back with no
   partial rows. Response embeds `queue_position`; `201` message
   "Appointment booked successfully".

### Overlap rule (half-open ranges, `409`)

`start_a < end_b and end_a > start_b` — back-to-back slots (one ends exactly
when the next starts) are legal. Both checks ignore `cancelled`/`no_show`
rows, so freed slots are re-bookable:

- **Barber-level:** same `barber_id` + `appointment_date` → `409`
  "Selected time conflicts with an existing appointment." Indexed by
  `ix_appointment_barber_date`.
- **Customer-level:** same `customer_id` + `appointment_date` (any barber) →
  `409` "You already have an appointment at this time."

### Reschedule (`PUT /api/v1/appointments/{id}` with `appointment_date?`/`start_time?`)

Re-derives `end_time` from the service duration and re-runs past-date, salon
hours, availability, and overlap checks **excluding the row itself**; terminal
(`completed`/`cancelled`) rows are immutable (`400`). Authz: owner, assigned
barber, or staff/admin (`403` otherwise); customers additionally cancel-only
for status changes.

### Duration handling (server-calculated)

The client never supplies a duration: `end_time` is derived per booking and
per reschedule. The wait estimate is Phase 5C SAWTE (`estimated_wait_minutes`
via `queue_service.estimate_for_entry`; `GET /queue/my-position` reports the
SAWTE `estimated_wait_minutes + confidence` — see §11 and §14).

### Status transitions, history wiring, cancel semantics

- Status vocabulary: `booked, confirmed, waiting, in_progress, completed,
  cancelled, no_show`. The service enforces a transition map (e.g.
  `booked → confirmed/cancelled/no_show`, terminal states immutable) with
  `400` on illegal jumps; the route additionally blocks any change to
  `completed`/`cancelled` rows (`400`) and restricts customers to
  `cancelled` (`403` otherwise).
- Every transition appends an `AppointmentStatusHistory` row
  (`old → new`); creation writes (`None → booked`); cancel writes
  (`booked → cancelled`). Book + cancel yields exactly 2 rows.
- The derived `Queue` row mirrors appointment status (service map:
  `in_progress → serving`, etc.; route copies the status verbatim on PUT).
- `DELETE /api/v1/appointments/{id}` is **cancel, not hard delete**:
  flips to `cancelled` with history + queue sync (`200`); already-cancelled
  is idempotent `200`; `completed` → `400`. (The service retains a
  `delete_appointment` hard-delete helper; no route calls it.)

### `409` semantics

`409 CONFLICT` is returned **only** for the two overlap cases (create and
reschedule), distinguished by message. Unknown barber/service/salon is
`404`; inactive entities, cross-salon mismatches, past slots, hours/window
violations are `400`; smuggled `end_time`/`customer_id` and bad
`booking_type`/date shapes are `422`; auth failures are `401`/`403`.
Failed bookings write nothing (no appointment, queue, or history rows).

## 11. Queue engine (Phase 4 — implemented)

Queue derivation in `app/services/queue_service.py`; HTTP contract in
`app/api/v1/queue.py`; appointment-side sync in
`app/services/appointments_service.py` (`_APPT_TO_QUEUE_STATUS`,
`_apply_status_transition`) and `app/api/v1/appointments.py`
(`_sync_queue_status`, `_record_history`). All responses use the uniform
envelope `{success, data, message}`.

### Lifecycle (appointment ↔ queue status map)

Appointment vocabulary (`APPOINTMENT_STATUSES`): `booked, confirmed,
waiting, in_progress, completed, cancelled, no_show`, enforced by
`STATUS_TRANSITIONS` (`booked → confirmed/cancelled/no_show`,
`confirmed → waiting/cancelled`, `waiting →
in_progress/cancelled/no_show`, `in_progress → completed`, terminal
`completed/cancelled/no_show` immutable) with `400` on illegal jumps.
Queue rows store `waiting | serving | completed | cancelled | no_show`
(`serving` is the queue-side alias of appointment `in_progress`;
`in_progress` is accepted on input and normalized to `serving`). The
mirror map is:

| Appointment | Queue row |
| --- | --- |
| `booked` / `confirmed` / `waiting` | `waiting` |
| `in_progress` | `serving` |
| `completed` / `cancelled` / `no_show` | same value verbatim |

Queue-level allowed edges (`_QUEUE_EDGES`, after normalization):
`waiting → serving/no_show/cancelled`, `serving → completed/cancelled`.
Rejected: `waiting → completed` directly (`400`), `serving → no_show`
(`400`), unknown statuses (`400`/`422` on `PUT`), any transition out of
a terminal state (`409`, incl. same-state repeat on a terminal row).
`cancelled`/`no_show` are terminal branches, never via serve/complete.

### Position rule (1-based, max+1, never reused)

Join computes `next_position = max(queue_position for the
appointment_date[, same barber]) + 1`, else `1`
(`queue_service._next_position_for_scope`: date scope always, barber
scope when `barber_id` is known; joins pass the appointment's barber so
operational ordering is per (date, barber) while legacy rows keep their
global per-day numbers). `ck_queue_position_positive` enforces
`queue_position >= 1`. No renumbering/compaction: cancelled/no-show/
completed rows keep their numbers and gaps persist; `count()` is never
used. `appointment_id` UNIQUE is the final double-join guard (`409`
"Appointment already has a queue entry").

### Scoping (salon + barber fields + query filters)

Every queue row carries `appointment_id` (unique, CASCADE — one row per
appointment), `salon_id` (nullable, SET NULL — deleting a salon must not
wipe queue history), `barber_id` (not null, CASCADE). `GET /queue` lists
active rows (`waiting`/`serving`/`in_progress` filter) ordered by
`queue_position ASC` with optional `?salon_id=&barber_id=&status=&date=`
filters (date joins appointments). Per-customer scoping lives in
`GET /queue/my-position` (own latest active appointment only);
`GET /queue/current` returns the smallest `serving`/`in_progress` row
for the scope (`200` + `null` "No customer currently being served" when
empty — never `404`/`500`).

### Serve-next + one-active guard (landed behavior)

- `POST /queue/serve-next` (`{barber_id*, salon_id?}`; missing
  `barber_id` → `422`, unknown barber → `404`): picks the smallest
  `queue_position` with status `waiting` for that (date=today, barber[+
  salon]) scope and transitions it `waiting → serving` (appointment →
  `in_progress`) with history + estimate recompute in one transaction.
  Empty scope → `404` "No waiting customers (in queue / for this
  barber)". **One-active guard enforced:** if a `serving` row already
  exists for the (date, barber[+ salon]) scope → `409` "Barber already
  has a customer in service" / "Another customer is already being served
  for this barber".
- `POST /queue/{id}/serve`: `waiting → serving` only (`400` when not
  waiting; `409` when the row is terminal or another `serving` row is
  active for the same (date, barber) — checked with `exclude_queue_id`).
- `POST /queue/{id}/complete`: `serving/in_progress → completed`
  (`400` "Cannot complete an entry that has not been served yet" when
  still `waiting`; `409` when terminal).
- `POST /queue/{id}/skip`: `waiting → no_show` only (`409` when the row
  is not `waiting` at the route layer; service raises `400` for
  non-waiting non-terminal, `409` for terminal).
- `PUT /queue/{id}` (`{status*}`): guarded transition via
  `_commit_transition` — status whitelist
  (`waiting/serving/in_progress/completed/cancelled/no_show`, else `422`;
  missing `status` → `422`) plus the edge/guard checks above; mirrors to
  the appointment, writes history, recomputes estimates.

### Wait formula (Phase 5C SAWTE — deterministic, history-based, no ML)

SAWTE (`app/services/sawte.py`, consumed via
`queue_service.estimate_for_entry` / `recompute_estimates_for_scope`) is a
deterministic history-based algorithmic/adaptive/historical moving-average
estimation. Canonical formula:

`estimate(requester) = serving_remaining + SUM(expected(ahead waiting))`

- `expected(a)` = historical moving average for the same barber+service
  (latest ≤ 5 completed appointments with
  `actual_duration_minutes IS NOT NULL`, newest first by `appointment_id
  DESC`; `avg = sum(window) / len(window)`), else the mandatory fallback
  `Service.duration_minutes` (missing service/duration → `0`, never a
  hardcoded average).
- `serving_remaining = max(0, ceil(expected(serving) − elapsed_minutes))`,
  where `elapsed_minutes = now − latest history.changed_at
  (new_status='in_progress')` for the serving appointment. No start stamp →
  `remaining = ceil(expected)` (never `Queue.joined_at`: join time ≠
  service-start time).
- Ahead scoping: same `barber_id` + `appointment_date`, status `waiting`,
  `queue_position < requester_position`, each contributing
  `ceil(expected)`. Ordered by `queue_position ASC`.
- Ceil policy: every component is `math.ceil`ed to whole minutes (never
  underestimate wait); measured durations use `max(1, ceil(delta))`.
- `GET /queue/my-position`: same scope math — `people_ahead` = waiting
  rows same (date, barber) with smaller position; `estimated_wait_minutes
  = wait_ahead (sum) + serving_remainder`; `currently_serving` = smallest
  `serving` position same (date, barber) (or `null`). Recomputed live on
  every join/serve/complete/skip/cancel for the affected scope and
  forwarded verbatim on WS pushes (the publisher performs no independent
  calculation — see §12). Full SAWTE detail (confidence, column,
  triggers, limits): see §14.

### Sync rule + history on every queue op

- Every queue transition goes through `_commit_transition`: validate edge
  → enforce one-active guard when entering `serving` → flip queue +
  appointment (queue `serving ↔` appointment `in_progress`) → stamp
  `updated_at` on both → append `AppointmentStatusHistory(old_appt →
  new_appt)` → flush → recompute estimates for the (date, barber) scope
  → commit once (rollback on any failure, no partials) → post-commit WS
  emit only (failed transactions emit nothing — see §12). Creation writes
  `None → booked`; serve writes e.g. `waiting → in_progress`; complete
  writes `in_progress → completed`; skip writes `waiting → no_show`.
- Appointment-side transitions (`PUT/DELETE /appointments`) mirror to the
  queue row and likewise append history.
- `DELETE /appointments/{id}` is cancel (`→ cancelled` + history + queue
  sync via `cancel_queue_for_appointment`, idempotent `200` when already
  terminal, `400` when completed); `404` when no queue row exists.

### RBAC

Operate endpoints require a non-customer role (`_require_operational`:
customer → `403`; barber/staff/admin pass) plus barber own-scope
(`_require_barber_scope` via `Barber.user_id`: barber operating on
another barber's row → `403` "Access denied"; `GET /queue` and
`GET /queue/current` filter to the caller's own `barber_id` and `403`
on explicit cross-barber query): `GET /queue`, `GET /queue/current`,
`PUT /queue/{id}`, `POST /queue/serve-next`,
`POST /queue/{id}/serve`, `POST /queue/{id}/complete`,
`POST /queue/{id}/skip` (`401` unauthenticated). `GET /queue/my-position`
is any authenticated user (own position only). "Receptionist" = the
`staff` role value (plus legacy `receptionist` accepted on WS/queue
paths), not a separate role.

### 404 / 409 conventions

- `404`: unknown queue `entry_id` ("Queue entry not found"), unknown
  appointment/barber/service/salon on booking paths, serve-next with no
  waiting rows ("No waiting customers…"), skip/cancel with no queue row.
- `409`: booking overlap (barber/customer, create/reschedule) **and**
  queue guards — serve/serve-next when another `serving` row is active
  for the (date, barber) scope, terminal-row transitions (incl. repeat on
  a terminal row), double-join (`appointment_id` UNIQUE), skip on a
  non-`waiting` terminal row. Message distinguishes the case. Other
  illegal queue edges are `400`; bad/unknown `PUT` status is `422`.

### Concurrency (transaction + FOR UPDATE attempt)

Booking and each queue op run in a single DB transaction
(commit-or-rollback, no partial rows). Overlap scans and position/next
lookups use deterministic ordering (`ORDER BY appointment_id`,
`ORDER BY queue_position ASC/DESC`). Mutating queue paths attempt a
row-level lock via `SELECT … FOR UPDATE` (`_try_for_update`, also used
by `serve_next` clash + next-row lookup) with try/except fallback to a
plain ordered SELECT — SQLite ignores it (single-writer lock +
transactional rollback keeps dev/test safe) while Postgres/MySQL get
real row-level exclusion; the `Queue.appointment_id` UNIQUE 1:1
constraint is the final double-join guard.

### Seed

`python seed.py` already seeds one `waiting` queue row
(`queue_position=1`, covering availability window + `None → booked`
history). Verified intact — no seed change needed.

### Phase 5B boundary (implemented next — see §13)

Read-only realtime is landed: WS snapshots + post-commit server-push
(`queue.updated` snapshot on connect; `queue.created/serving/completed/
skipped/cancelled/updated` broadcasts for REST mutations; single-instance
fan-out, Redis future). Notifications fan-out is also landed (§13: the same
post-commit `queue_events` feed drives per-user records; queue never rolls
 back on notification failure). Still out of scope: demand analytics/BI, priority
 queues, multi-branch queues. Do not document any as present. SAWTE
 estimation is landed (§14) — deterministic history-based only, never ML.

## 12. Realtime queue WebSocket (Phase 5A — implemented, read-only push)

Endpoint: `WS /api/v1/ws/queue/{salon_id}?token=<JWT>&barber_id=<int>&date=YYYY-MM-DD`
(`app/api/v1/queue_ws.py` → `app/ws/manager.py` + `app/ws/events.py`;
mounted in `app/api/v1/router.py`; publisher `app/services/queue_events.py`).
**REST remains the mutation path** — the socket accepts no mutation API:
client messages are received and ignored (no echo/broadcast of untrusted
content); every state change happens via REST (`POST /appointments`,
`POST /queue/serve-next`, `POST /queue/{id}/serve|complete|skip`,
`PUT /queue/{id}`, `DELETE /appointments/{id}`) and is pushed post-commit.

### Query auth + close codes (JWT reuse, no new auth)

- `?token=` carries the same JWT as REST (`decode_access_token` only;
  `Authorization: Bearer` header is **not** read on WS). `barber_id` and
  `date` are optional scope params; `date` defaults to today.
- Auth failures close with `4401` (missing token, invalid/tampered token,
  expired token, unknown `sub`): reason is a short non-leaky string
  ("Missing token" / "Invalid or expired token"). No tracebacks.
- Bad `date` shape closes with `4400` ("Invalid date, use YYYY-MM-DD").
- Unknown `salon_id` closes with `4404` ("Salon not found").
- Authorization failures close with `4403` ("Access denied" /
  "Barber profile not found" / "Insufficient permissions").

### RBAC scoping (channel = `(salon_id, barber_id, date)`)

- `customer`: own-scope only — snapshot is own latest queue row for the
  scope (`has_queue/my_queue_id/my_position/my_status/people_ahead/
  estimated_wait(_minutes)/current_serving/currently_serving/scope`) plus
  the serving summary; never other customers' rows. Foreign salon with no
  own queue returns authorized empty scope (`has_queue: false`), not a
  close — the isolation property is no foreign ids/positions leak.
- `barber`: own `barber_id` only (resolved via `Barber.user_id`; no
  `barber_id` defaults to own). Requesting another `barber_id` → `4403`;
  missing profile → `4403`. Receives the full entry list for the scope.
- `staff` / `receptionist` / `admin`: full salon scope (any `barber_id`;
  `barber_id=None` subscribes salon-wide and receives every barber
  channel in that salon+date). Receives `entries[] + current_serving/
  currently_serving + scope`.
- Unknown role values → `4403`.

### Event types / payloads (no PII by construction)

Wire envelope is always `{"event": <name>, "data": <payload>}`
(`app/ws/events.py::build_event`; `QueueEvent` schema). Names:

| Event | When (post-commit REST trigger) |
| --- | --- |
| `queue.updated` | Initial snapshot on connect; generic update / wait-recompute fallback |
| `queue.created` | Booking / join committed a new `waiting` row |
| `queue.serving` | `waiting → serving` (incl. `serve-next`) |
| `queue.completed` | `serving → completed` |
| `queue.skipped` | `waiting → no_show` (skip) |
| `queue.cancelled` | `waiting/serving → cancelled` (cancel sync) |
| `queue.position_changed` | Position/estimate scope update (reserved; forwarded as `queue.updated` when unroutable) |

Payload allowlist only (`sanitize_payload` strips everything else;
datetimes → ISO): `queue_id, appointment_id, barber_id, salon_id,
queue_position, status, current_serving/currently_serving,
estimated_wait/estimated_wait_minutes, people_ahead, my_position,
my_status, my_queue_id, has_queue, scope{salon_id,barber_id,date},
entries[], updated_at, event_version`. Staff/barber snapshots use
per-entry `entry_payload` (same fields + `current_serving`); customer
snapshots additionally strip other customers' `appointment_id` values.
**Never included:** `password/password_hash` (`$2b$`/`$2a$`), JWT/token/
`access_token`/`jwt_secret`/`secret_key`, `phone`/`email`/names or any
other PII. Publisher (`queue_events.build_event/event_from_rows`)
forwards `queue_position`/`estimated_wait_minutes` verbatim from the
committed rows — it performs no independent calculation.

### Lifecycle / reconnect

Connect → auth → authorize → `manager.connect` (`accept` + register
`(salon_id, barber_id, date, user_id, role)`) → server sends the initial
authorized `queue.updated` snapshot via `send_personal` → server-push
wait loop (`receive_text` parked; protocol auto-pong is the heartbeat —
no app-level ping) → `disconnect` cleanup on close/error. Reconnect is a
fresh connect (new snapshot; no resume token / no replay buffer): clients
should reconnect with backoff + jitter on drop and re-render from the new
snapshot, then apply pushed events. Failed mutations emit nothing
(post-commit only — a `400/409/422` REST failure produces no WS event);
each successful mutation emits exactly one event. `send_*/broadcast_*`
never raise: dead sockets are pruned and the remaining sends continue, so
one bad client cannot crash a broadcast.

### Single-instance limitation + Redis future

`ConnectionManager` is a process-local singleton (`manager`): each
worker/replica serves only its own sockets — no cross-process fan-out
today. `broadcast_to_queue(barber_id, date[, salon_id])` (salon-wide
subscriptions with `barber_id=None` receive every barber in the salon)
and `broadcast_to_salon(salon_id[, date])` fan out to local matches;
`broadcast_event` routes publisher envelopes (`{type,version,scope,data}`)
to the matching channel (unknown types fall back to `queue.updated`).
Future: back `broadcast_*` with Redis pub/sub (publish event + channel,
subscribe per instance, fan out locally) without changing call sites.
In-process `queue_events` outbox + `subscribe/unsubscribe` bridge already
isolates REST from WS: REST appends + notifies, the WS connection
subscribes for its lifetime and unsubscribes on disconnect (no leaks);
publish errors are logged only and never break REST.

## 13. Notifications (Phase 5B — implemented)

Fan-out lives in `app/notifications/` (service + providers + templates +
prefs + durable model); HTTP contract in `app/api/v1/notifications.py`
(history GET only); wiring in `app/main.py` lifespan
(`subscribe_notifications` / `unsubscribe_notifications`). All responses use
the uniform envelope `{success, data, message}`.

### Architecture (post-commit consumer, no second bus)

- `NotificationService.handle(queue_event)` is subscribed to
  `app/services/queue_events.subscribe` — the **same** post-commit feed that
  drives WS push. There is **no second bus / no new queue**.
- All `publish_*` helpers run **after** `db.commit()` succeeds, so a failed
  booking/queue transaction emits nothing (no `queue_events` entry, no
  notification record).
- Notification failure **never rolls back the queue**: `handle()` never
  raises and never mutates queue/appointment rows — it only reads
  Queue/Appointment/User (own short-lived session) and writes notification
  records/outbox. Provider exceptions are caught, truncated, marked FAILED;
  REST `201/200` stands.
- Recipient resolution: `appointment_id` → appointment → `customer_id` →
  `User` (first name = first token of `name`); falls back to explicit
  `user_id`/`customer_id` carried in the event (tests). Unresolvable →
  skip quietly.

### Providers (mock default, real disabled without creds)

Contract in `app/notifications/providers/base.py` (`send() -> Result`,
never raises by itself). Selection in `providers/__init__.py::get_provider`:

- Default (`{CH}_ENABLED=false`, which is the shipped default): Mock
  providers (`MockEmailProvider` / `MockPushProvider` / `MockSmsProvider`) —
  record the send in-memory (`SENT[]`) and return success. Never touch the
  network; dev/tests observable without any external call.
- Real stubs (`SmtpEmailProvider` via `smtplib` inline, `HttpPushProvider`,
  `HttpSmsProvider`) activate **only** when `{CH}_ENABLED=true` **plus**
  host creds (`{CH}_HOST` + `{CH}_USER` + `{CH}_PASS`) exist. Otherwise they
  return `Result(success=False, ...)` (`"... disabled"` / `"... credentials
  missing"`) — never raise, never send. Secrets are never logged (host/port
  only on failures).
- Email real path performs the `smtplib` send inline with short timeout and
  no provider-level retries (the service bounds retries); push/SMS real
  stubs are wiring-only (stubbed success once enabled; replace with gateway
  call when credentials are provisioned).
- **Real-provider limits (mock validated only):** only the mock path is
  validated by tests; no live gateway delivery has been verified. Do not
  claim production email/push/SMS delivery.

### Types / channels

Channels (`Channel` enum, N1-owned in `preferences.py`): `email`, `push`,
`sms`. Types (`NotificationType`): `appointment_booked`,
`appointment_cancelled`, `queue_joined`, `queue_approaching`, `turn_now`,
`appointment_completed`. Templates in
`app/notifications/templates/templates.py` render `(subject, body)` from
`{first_name}` / `{position}` / `{wait_minutes}` only; `render()` never
raises and degrades to a generic body.

### Triggers mapping (queue event → notification type)

In `app/notifications/service.py` (`EVENT_TO_TYPE` + `_map_event`):

| Queue event (post-commit) | Notification type | Notes |
| --- | --- | --- |
| `queue.created` | `queue_joined` | Booking / join committed a new `waiting` row |
| `queue.serving` | `turn_now` | `waiting → serving` (incl. `serve-next`); security type — bypasses prefs |
| `queue.completed` | `appointment_completed` | `serving → completed` |
| `queue.cancelled` | `appointment_cancelled` | `waiting/serving → cancelled` (cancel sync); appointment-domain `appointment.cancelled` maps identically (forward-compat) |
| `queue.updated` with `queue_position <= APPROACHING_THRESHOLD` (default `2`) | `queue_approaching` | Position gate; `queue.updated` beyond the threshold is a silent position refresh (no record) |
| `queue.skipped` (`no_show`) | — (silent) | No customer message by default |

`APPT_EVENT_TO_TYPE` maps `appointment.booked → appointment_booked` (and
cancelled/completed equivalents) for forward-compat; no publisher emits
them yet.

### Idempotency key

Built by `app/notifications/models.py::build_idempotency_key`:
`"<type>:<appointment_id>:<channel>"` (or verbatim `event:<event_id>` when
the event carries a stable id). Enforced two layers: in-process `_SEEN_KEYS`
dedupe plus DB `UNIQUE uq_notifications_idempotency_key` — concurrent
duplicate inserts raise `IntegrityError`, treated as already-queued
(existing row id returned, no blind retry). Re-delivery of the same queue
transition collapses to one row.

### Bounded retry (max 3, no celery, no sleep)

`MAX_ATTEMPTS = 3` (`app/notifications/models.py`; `service.MAX_ATTEMPTS`
mirrors it). The service loops at most 3 inline attempts per channel (no
background worker, no sleep/backoff). `Notification.can_retry` encodes the
bound (`attempts < MAX_ATTEMPTS`). Exhausted sends land as `FAILED` with
truncated error; REST is unaffected.

### Persistence table + statuses

Table `notifications` (`app/notifications/models.py`, migration
`a91f3c7e2b44_add_notifications_table.py`): `notification_id` PK,
`user_id` → `users.user_id` (SET NULL, nullable), `appointment_id` →
`appointments.appointment_id` (SET NULL, nullable), `queue_id` →
`queue.queue_id` (SET NULL, nullable), `channel` (`String(20)`),
`type` column (attr `notification_type`, `String(40)`), `status`
(`PENDING`/`SENT`/`FAILED`, check `ck_notifications_status_allowed`),
`template_ref`, `attempts` (`>= 0`), `error` (`Text`, ≤ 500 chars via
`truncate_error`), `idempotency_key` (`String(255)`, unique
`uq_notifications_idempotency_key`), `created_at`, `sent_at` (nullable).
Indexes: `ix_notifications_status_created (status, created_at)`,
`ix_notifications_type_channel (type, channel)`. FK-only, no ORM
relationships (owning sides untouched). Graceful outbox-only fallback when
the table is unavailable (`OUTBOX[]` in-memory mirror retains every record
this process creates).

### Preferences defaults

In `app/notifications/preferences.py` (in-memory store until a prefs table
lands; `is_channel_enabled` is the only read path the service uses):
defaults are **email ON, push ON, sms OFF**. `SECURITY_TYPES = {turn_now}`
bypasses prefs (always delivered, even when all channels toggled off).
Unknown users fall back to channel defaults; unknown channel raises
`ValueError`.

### Privacy (no PII beyond position / first name)

Templates render first name (first token, ≤ 50 chars) + `queue_position` +
`estimated_wait_minutes` only. Never included in bodies/logs/records:
`password`/`password_hash`, JWT/token/`access_token`/`secret`, `phone` /
`email` / full names as message content, or provider credentials. Errors
stored via `truncate_error` are safe bounded strings (never secrets/tokens).
Addressing is channel-minimal: email → user email, SMS → user phone, push
→ user id (device fan-out is gateway-side).

### History GET RBAC (no send endpoint)

`GET /api/v1/notifications?limit=&offset=` (defaults `50` / `0`, max
`limit 200`) is the **only** notification endpoint — there is **no POST /
send endpoint**. Auth via `get_current_user`; uniform envelope. RBAC:
`admin` sees all rows, `customer` sees only own `user_id` rows (other
customers' rows filtered, `200` isolated — never `404`), every other role
(`barber`, `staff`/receptionist) gets `403`, unauthenticated gets `401`.
Reads persisted rows ordered `notification_id DESC` with pagination slice;
falls back to reversed `OUTBOX` when the DB table is unavailable.

### WS vs notification split

| Concern | WS realtime (Phase 5A) | Notifications (Phase 5B) |
| --- | --- | --- |
| Feed | `queue_events` post-commit → `ConnectionManager` fan-out | Same `queue_events` post-commit → `NotificationService.handle` |
| Audience | Salon/barber/date channel sockets (ephemeral) | Per-user durable records (inbox + history GET) |
| Payload | Positional snapshots (`entries[]`, serving summary, no PII) | Per-user templated message (first name + position + wait) |
| Lifecycle | Reconnect = fresh snapshot, no replay | Idempotent persisted rows (`PENDING/SENT/FAILED`), retry ≤ 3 |
| Failure | Dead sockets pruned, broadcasts never raise | Provider failures → FAILED, never raise, queue never rolls back |

Both consumers perform no independent wait calculation — they forward the
committed `queue_position` / `estimated_wait_minutes` from `queue_service`.

### Real-provider limits (mock validated only)

Only the mock path is exercised by `backend/tests/test_notifications.py`
(success + recording, disabled-stub failure Results, raising-provider
isolation, no real sends even with network blocked). Real stubs require
operator-provisioned creds and have no live-gateway verification; push/SMS
stubs perform no external call yet by design.

### Phase 5C boundary (no analytics)

Phase 5C adds SAWTE estimation only (§14) — still no demand analytics, no BI
dashboards. Also still out: payments, ratings/reviews,
multi-branch, mobile apps, user-managed preference endpoints,
multi-language templates.

## 14. SAWTE estimation (Phase 5C — implemented, deterministic, not ML)

SmartQueue Wait Time Estimator in `app/services/sawte.py`, integrated via
`app/services/queue_service.py` (`estimate_for_entry`,
`recompute_estimates_for_scope`, `get_confidence_for_entry`). This is a deterministic history-based algorithmic/adaptive/historical moving-average estimation — pure arithmetic over measured durations. It is **not** ML:
no models, no training, no learned weights, no inference endpoints, no
`sklearn`/`numpy` dependency.

### Formula (canonical)

`estimate(requester) = serving_remaining + SUM(expected(ahead waiting))`

- `expected(pair)` for a (barber, service) pair = historical moving average
  when history exists, else the mandatory fallback
  `Service.duration_minutes` (missing service/duration → `0`, never a
  hardcoded average).
- Historical average = `sum(latest ≤ 5 completed durations) / len(window)`
  over completed appointments with the same `barber_id` + `service_id`
  where `actual_duration_minutes IS NOT NULL`, newest first by
  `appointment_id DESC`. `total_count` counts all matching rows (beyond the
  window); the average covers only the window.
- `serving_remaining = max(0, ceil(expected(serving) − elapsed_minutes))`
  with `elapsed_minutes = now − latest AppointmentStatusHistory.changed_at
  (new_status='in_progress')` for the serving appointment. No start stamp →
  `remaining = ceil(expected)` (never `Queue.joined_at`). Negative elapsed
  (clock skew) clamps to `0` elapsed; non-positive remainder returns `0`.
- Ahead rows: same `barber_id` + `appointment_date`, status `waiting`,
  `queue_position < requester_position`, each contributing
  `ceil(expected)`. Ordered by `queue_position ASC`.
- Ceil policy: every component uses `math.ceil` to whole minutes (never
  underestimate wait). Measured durations use `max(1, ceil(delta))` so
  sub-minute services still record 1 minute.

### Measured-duration column + migration

- `appointments.actual_duration_minutes` (`Integer`, nullable, no default,
  no check, no index) — `NULL` = unknown. Old rows stay valid; the
  estimator falls back to `Service.duration_minutes` when the window is
  empty.
- Populated once on complete inside the same `_commit_transition`
  transaction: serving start = latest history `changed_at` with
  `new_status='in_progress'` (fallback `Queue.joined_at` when no such row
  exists); `actual = compute_actual_minutes(start, now)`. Same-commit write
  — never a separate transaction.
- Migration `c9d1e2f3a4b5_add_actual_duration_minutes.py` (revises
  `a91f3c7e2b44`): `batch_alter_table` adds the nullable column; downgrade
  drops it. SQLite-safe; mirrors the model so `alembic check` reports no
  drift.

### Confidence (data availability, not probability)

Each component (the serving row + every ahead waiting row) maps its pair's
`total_count` to `LOW` (0–2) / `MEDIUM` (3–5) / `HIGH` (6+). Request
confidence = weakest (`min`) over components. Zero components (empty queue
ahead + no serving) → `LOW`, because zero historical records are involved.
Confidence is transient: computed on read via `get_confidence_for_entry` /
`estimate_for_entry`, forwarded verbatim, never persisted (no `Queue`
column). It describes how much history backs the estimate — it is not a
probability and not an accuracy guarantee.

### API: `my-position` (back-compatible) + queue rows

- `GET /queue/my-position` returns the existing fields plus `confidence`:
  `{has_queue, queue_position, status, people_ahead,
  estimated_wait_minutes, currently_serving, appointment_status,
  confidence}` (plus legacy `current_position` alias of
  `currently_serving`). Old clients ignore the new key; no field was
  removed or renamed.
- `QueueResponse` / `MyPositionResponse` carry optional `confidence`
  (`None` when not computable). List/detail serialization attaches it via
  `get_confidence_for_entry` on a best-effort path that never raises, so
  serialization cannot break REST.

### WS: confidence verbatim

`app/ws/events.py` allowlists `confidence` (no other new keys).
`entry_payload` / `build_event` / `sanitize_payload` forward it verbatim
from the committed rows (`queue_position` / `estimated_wait_minutes` +
`confidence`); the publisher performs no independent calculation. No PII
change: still ids/positions/statuses/waits/scope/entries only.

### Recalc triggers (existing post-commit bus, no second bus)

Estimates are recomputed by `recompute_estimates_for_scope(date, barber)`
(flushing, no commit; the caller owns the transaction) on every mutation
that affects the scope: join, serve, serve-next, complete, skip, PUT
transition, appointment cancel sync. All `publish_*` helpers in
`app/services/queue_events.py` run **after** `db.commit()` succeeds, so a
failed transaction emits nothing and a successful one emits exactly one
event; estimate failures never break REST (skipped row, logged publish
error). There is no second bus and no background worker.

### Limitations (read before relying on the number)

- New barber+service combos have no history → fallback to
  `Service.duration_minutes` with `LOW` confidence until completions
  accumulate.
- The estimate does not model delays, breaks, walk-in surges, or
  mid-service interruptions — it only sees measured past durations plus
  the current scope rows.
- Confidence describes data availability (`total_count` bands), not
  certainty or probability.
- The estimate is not a guarantee: it is a planning aid recomputed live as
  the scope changes; the stored `estimated_wait_minutes` column stays an
  `int` as before and is refreshed on every in-scope mutation.

Frontend untouched: Phase 5C changes backend estimation, REST
(`my-position` + `QueueResponse` additive `confidence`), and WS payloads
only. No frontend file was modified for this phase.
