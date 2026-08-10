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
- Health check: `http://localhost:8000/api/health`

### Frontend

```bash
cd frontend
npm install
npm run dev     # http://localhost:5173 (proxies /api -> http://localhost:8000)
```

### Seeded demo accounts

| Role | Email | Password |
| --- | --- | --- |
| Admin | `admin@salon.com` | `Admin@123` |
| Customer | `jerome@salon.com` | `Jerome@123` |

### Running tests

```bash
cd backend
pytest -v
```

## Database & migrations

By default the app uses SQLite (`backend/smartqueue.db`). For MySQL, set `DATABASE_TYPE=mysql` plus host/port/user/password/name in `backend/.env`.

Initial tables are auto-created on startup (`Base.metadata.create_all`). For schema changes Alembic is configured:

```bash
cd backend
alembic revision --autogenerate -m "message"
alembic upgrade head
```

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