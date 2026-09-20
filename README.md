# SmartQueue — Barbershop Appointment & Queue Management Platform

## 1. Project Overview

SmartQueue is a full-stack web application that lets customers book barbershop appointments online and track their position in a live queue, while staff and admins manage services, barbers, appointments, and the queue in real time.

The system allows customers to:

- Register an account and log in securely
- Browse active services (with price and duration) and barbers (with specialization)
- Book an appointment against a specific barber, date, and time slot
- Track their live queue position and estimated wait time

The system automatically prevents double booking and assigns each booking a per-day queue number.

The platform reduces the time customers spend waiting in the shop and gives the salon a centralized system for managing bookings and the queue in one place.

---

## 2. Main Features

### Customer

- Register and login securely
- Manage profile (name, email, phone)
- Browse services and barbers
- Book appointments (single barber slot per date/time, double-booking prevention)
- Live queue position with estimated wait time (auto-refreshing every 10s)
- Cancel own appointments

### Admin / Staff

- Live queue management with serve / complete actions
- Full CRUD for services and barbers
- View and update all appointments
- Admin dashboard with queue, services, barbers, and appointments tabs

### Guest

- View active services and barbers without logging in

---

## 3. Booking & Queue Management

The application provides an automated queue assignment and live tracking mechanism.

1. A customer books an appointment for a specific barber, date, and time.
2. Double booking is prevented by a unique constraint on (barber, date, time) plus an application-level check that ignores cancelled/no-show slots.
3. Each appointment is automatically assigned the next queue number of the day (1, 2, 3, ...).
4. The customer's estimated wait time is the number of people ahead times the service duration.
5. Staff move entries from waiting → serving → completed, and the linked appointment status updates consistently.

---

## 4. Technology Stack

### Frontend

- React 19
- Vite
- Tailwind CSS 4
- React Router 7
- Axios

### Backend

- Python 3.12+
- FastAPI
- SQLAlchemy 2.0
- Alembic
- Pydantic (v2)
- python-jose (JWT)
- bcrypt

### Database

- SQLite (default) or MySQL via PyMySQL

### API

- RESTful APIs at `/api/v1`
- Swagger UI at `/docs`, ReDoc at `/redoc`
- Uniform JSON response envelope: `{ "success": boolean, "data": ..., "message": "..." }` across all endpoints

### Testing

- pytest + `fastapi.testclient` (httpx)

### Development Tools

- Visual Studio Code
- Postman (API testing)
- Git
- GitHub

---

## 5. System Architecture

The application follows a three-layer architecture:

```text
React Frontend (Vite)
      |
      | REST API /api/v1  (proxied in dev)
      v
FastAPI Backend
      |
      | SQLAlchemy ORM
      v
SQLite / MySQL Database
```

See [docs/architecture.md](docs/architecture.md) for details and [docs/diagrams](docs/diagrams) for the architecture, ER, and class diagrams.

---

## Quick start

### Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate   |  Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env

# Seed sample data (admin + customer + barbers + services)
python seed.py

# Run the API
uvicorn app.main:app --reload --port 8000
```

- API base URL: `http://localhost:8000/api/v1`
- Swagger UI: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/api/health` (envelope `{success, data, message}` + `database: up/down` DB probe; 503 when DB is down)

### Frontend

```bash
cd frontend
npm install
npm run dev     # http://localhost:5173 (proxies /api -> http://localhost:8000)
```

The frontend API base URL is configured via `VITE_API_BASE_URL` (see `frontend/.env.example`):
- Dev: `VITE_API_BASE_URL=/api/v1` (relative, uses the Vite proxy)
- Production: `VITE_API_BASE_URL=https://<your-render-api>/api/v1`

### Seeded demo accounts

| Role | Email | Password |
| --- | --- | --- |
| Admin | `admin@salon.com` | `Admin@123` |
| Customer | `jerome@salon.com` | `Jerome@123` |

## Running Tests

```bash
cd backend
python -m pytest -v    # or just: pytest -v
```

Tests run against an isolated temporary SQLite database, so no setup or local DB state is required.

## Database & migrations

By default the app uses SQLite (`backend/smartqueue.db`). For MySQL, set `DATABASE_TYPE=mysql` plus host/port/user/password/name in `backend/.env`. For production (e.g. Render Postgres), set a full `DATABASE_URL` — it takes precedence over the field-based settings.

Initial tables are auto-created on startup via the lifespan handler (`Base.metadata.create_all`). The baseline schema is also captured as an Alembic migration (`backend/alembic/versions/*_initial_schema.py`):

```bash
cd backend
alembic upgrade head            # apply baseline (verified on fresh SQLite)
alembic revision --autogenerate -m "message"   # schema changes
alembic upgrade head
```

## Environment Variables

The app is configured through environment variables (loaded from a `.env` file). Example files exist at the repository root (`.env.example`) and in `backend/.env.example`. All variables listed below have sensible defaults except `JWT_SECRET_KEY`.

| Variable | Description | Required |
| --- | --- | --- |
| `DATABASE_URL` | Full DB URL override (e.g. `postgresql+psycopg2://...` on Render). Takes precedence when set | N |
| `DATABASE_TYPE` | Database dialect: `sqlite` (default) or `mysql` (fallback when `DATABASE_URL` is empty) | N |
| `DATABASE_HOST` | Database host (MySQL only) | N |
| `DATABASE_PORT` | Database port (MySQL only) | N |
| `DATABASE_USER` | Database user (MySQL only) | N |
| `DATABASE_PASSWORD` | Database password (MySQL only) | N |
| `DATABASE_NAME` | Database name (MySQL only) | N |
| `JWT_SECRET_KEY` | Secret used to sign/verify JWTs | Y |
| `JWT_ALGORITHM` | JWT algorithm (default `HS256`) | N |
| `JWT_EXPIRE_MINUTES` | Access token lifetime in minutes | N |
| `APP_NAME` | Application display name | N |
| `APP_VERSION` | Application version string | N |
| `DEBUG` | Enable debug mode (`true`/`false`) | N |
| `CORS_ORIGINS` | Comma-separated allowed CORS origins (e.g. `https://app.vercel.app,http://localhost:5173`) | N |
| `VITE_API_BASE_URL` | Frontend API base URL (frontend `.env`; `/api/v1` for dev, full Render URL for prod) | N |
| `VITE_WS_BASE_URL` | Optional independent WebSocket base (`wss://.../api/v1`); derived from `VITE_API_BASE_URL`/page origin when unset | N |
| `APP_ENV` | Set `production` on the host to activate production guards (JWT-secret check); empty locally | N |

## Deployment & CI

- Backend (Render): `render.yaml` builds `backend/requirements.txt` and starts with `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Set `DATABASE_URL`, `JWT_SECRET_KEY`, and `CORS_ORIGINS` (your Vercel URL) in the Render dashboard. Health check path: `/api/health`.
- Frontend (Vercel): `frontend/vercel.json` builds with `npm run build` (output `dist`). Set `VITE_API_BASE_URL=https://<your-render-api>/api/v1` in the Vercel project settings.
- CI: `.github/workflows/backend.yml` runs pytest, ruff, `pip check`, and a fresh-SQLite `alembic upgrade/downgrade/upgrade` cycle; `.github/workflows/frontend.yml` runs `npm ci`, `npm run lint`, and `npm run build`.

## API Documentation

FastAPI auto-generates interactive docs once the backend is running:

- Swagger UI: <http://localhost:8000/docs>
- ReDoc: <http://localhost:8000/redoc>

All business endpoints are served under the base path `/api/v1`, and the health check lives at `/api/health`.

## API overview

| Method | Path | Access | Description |
| --- | --- | --- | --- |
| POST | `/auth/register` | Public | Register a customer, returns JWT |
| POST | `/auth/login` | Public | Login, returns JWT |
| GET | `/auth/me` | Any authenticated | Current user profile |
| GET | `/services` | Public | List active services |
| POST/PUT/DELETE | `/services/{id}` | Admin | Manage services |
| GET | `/barbers` | Public | List barbers |
| POST/PUT/DELETE | `/barbers/{id}` | Admin | Manage barbers |
| GET/POST | `/appointments` | Authenticated | List / create appointments |
| PUT | `/appointments/{id}` | Owner / staff | Update status (customers may only cancel) |
| GET | `/queue` | Admin/Staff | Live waiting/serving queue |
| GET | `/queue/my-position` | Any authenticated | Customer's queue position & wait time |
| PUT | `/queue/{id}` | Admin/Staff | Update queue entry status |
| POST | `/queue/{id}/serve` | Admin/Staff | Move entry to serving |
| POST | `/queue/{id}/complete` | Admin/Staff | Complete an entry |

## Documentation

- [Problem statement](problemstatement.md)
- [Architecture](docs/architecture.md)
- [Diagrams](docs/diagrams/) — architecture, ER, and class diagrams
- [Changelog](CHANGELOG.md)

## License

See [LICENSE](LICENSE).