# Changelog

All notable changes to this project are documented in this file.

## [0.3.0] - 2026-09-14

### Added
- Alembic baseline migration `initial schema` (users, barbers, services, appointments, queue); verified `upgrade head` / `downgrade -1` / `upgrade head` on fresh SQLite
- CI workflows: `backend.yml` (pytest + Alembic upgrade cycle) and `frontend.yml` (`npm ci` + lint + build)
- Deploy configs: `render.yaml` (Render backend, `alembic upgrade head` on start, `/api/health` check) and `frontend/vercel.json` (Vite build, SPA rewrites)
- Env examples: `DATABASE_URL` override + `CORS_ORIGINS` docs in root/`.env.example` and `backend/.env.example`; `frontend/.env.example` with `VITE_API_BASE_URL`
- Postgres driver `psycopg2-binary` for `DATABASE_URL` deployments

### Changed
- Backend lifespan handler replaces deprecated `@app.on_event("startup")`
- `GET /api/health` returns the uniform `{success, data, message}` envelope with a `SELECT 1` DB probe (`database: up`, 503 + `database: down` on failure)
- Config: `DATABASE_URL` env override takes precedence; `CORS_ORIGINS` parsed as comma-separated string; non-SQLite URLs use pooled engine with `pool_pre_ping`
- Frontend axios base URL reads `VITE_API_BASE_URL` (falls back to `/api/v1` for the Vite dev proxy)

### Fixed
- `test_auth.py`: accept valid unauthorized response codes for missing bearer token

## [0.2.0] - 2026-08-12

### Added
- Uniform JSON response envelope `{success, data, message}` across all API endpoints
- Business-logic services layer (app/services: appointments_service, queue_service) with thin routers

### Changed
- README: environment variables table, running-tests command, API docs links

### Fixed
- Frontend axios unwraps the response envelope so pages work unchanged

## [1.0.0] - 2026-08-12

### Added
- Project scaffolding with FastAPI backend and React frontend
- Database models (users, barbers, services, appointments, queue)
- JWT authentication (register/login) with bcrypt password hashing
- Service and Barber CRUD APIs (admin-only writes)
- Appointment booking with double-booking prevention and queue-number assignment
- Queue management system (serve / complete / live queue)
- Customer dashboard with live queue status
- Admin dashboard with queue, services, barbers, appointments management
- Responsive UI with Tailwind CSS
- Database seed script (`backend/seed.py`) with demo admin/customer accounts

### Documentation
- Root `README.md` with setup instructions and API overview
- `docs/architecture.md` with architecture overview and decisions
- `docs/diagrams/` with Mermaid diagrams (architecture, ERD, booking flow, queue lifecycle, auth flow)
- Frontend README with scripts and structure

### Testing
- pytest suite covering auth, services, barbers, appointments, and queue lifecycle
- Isolated test database (temp SQLite) and TestClient fixtures