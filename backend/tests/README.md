# SmartQueue Tests

pytest suite for the FastAPI backend.

## Run

```bash
cd backend
pytest -v
```

The suite uses an isolated in-memory SQLite database (via `conftest.py`), so it never touches the development `smartqueue.db`.

## Fixtures (backend/tests/conftest.py)

| Fixture | Purpose |
| --- | --- |
| `db_engine` | In-memory SQLite engine, tables created/dropped per test |
| `db_session` | Scoped test session |
| `client` | `fastapi.testclient.TestClient` with `get_db` overridden to the test session |
| `admin_user` / `customer_user` | Seeded roles |
| `admin_headers` / `customer_headers` | Bearer tokens for API calls |
| `seeded_data` | A barber + a service for booking tests |

## Coverage

- **auth** — register, duplicate email, login, wrong password, `/me`
- **services** — public list/get, admin-only create/update/delete, 403 for customers
- **barbers** — public list/get, admin-only CRUD, 403 for customers
- **appointments** — create, past-date rejection, double-booking conflict, single-booking-per-slot, customer cancel-only rules, per-user listing scope
- **queue** — staff access control, no-queue position, live position, serve → complete lifecycle