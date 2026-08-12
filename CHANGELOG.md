# Changelog

All notable changes to this project are documented in this file.

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