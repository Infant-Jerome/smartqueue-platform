# SmartQueue — Diagrams

This folder contains the rendered diagrams (PNG), their editable sources (`.drawio` / `.dbml` / `.mmd`), and the Mermaid sources below as text fallbacks. Open the `.drawio` files in <https://app.diagrams.net>, the `.dbml` file in <https://dbdiagram.io>, and the `.mmd` file at <https://mermaid.live>.

| Diagram | PNG | Editable source |
| --- | --- | --- |
| System architecture | [SmartQueueArchi.png](./SmartQueueArchi.png) | [SmartQueueArchi.drawio](./SmartQueueArchi.drawio) |
| Entity Relationship | [SmartQueueER.png](./SmartQueueER.png) | [SmartQueueER.dbml](./SmartQueueER.dbml), [SmartQueueER.mmd](./SmartQueueER.mmd) |
| UML class diagram | [SmartQueueClassDia.png](./SmartQueueClassDia.png) | [SmartQueueClassDia.drawio](./SmartQueueClassDia.drawio) |

The Mermaid sources below render the same content at https://mermaid.live or in any Mermaid-capable viewer.

---

## 1. System architecture

```mermaid
sequenceDiagram
    autonumber
    participant U as Browser (React SPA)
    participant V as Vite dev proxy (:5173)
    participant A as FastAPI (:8000 /api/v1)
    participant DB as SQLite / MySQL

    U->>V: GET /api/health
    V->>A: proxy request
    A->>A: CORS + routers
    A->>DB: engine / session
    DB-->>A: rows
    A-->>U: JSON response
```

```mermaid
flowchart LR
    subgraph Frontend
        REACT[React 19 SPA]
        AXIOS[Axios client + JWT interceptor]
    end
    subgraph Backend
        FA[FastAPI app]
        ROUTERS[api/v1 routers<br/>auth services barbers appointments queue]
        SCHEMA[Pydantic schemas]
        DEPS[security + role deps]
        ORM[SQLAlchemy ORM]
    end
    subgraph Data
        AL[SQLite smartqueue.db]
        MY[MySQL]
    end

    REACT --> AXIOS
    AXIOS -->|/api/v1/*| FA
    FA --> ROUTERS
    ROUTERS --> SCHEMA
    ROUTERS --> DEPS
    ROUTERS --> ORM
    ORM --> AL
    ORM -. optional .-> MY
```

---

## 2. Entity Relationship Diagram (ERD)

The ER diagram visualizes the 5-table schema. `appointments` is the central entity linking customers, barbers, and services, while `queue` provides 1:1 live queue tracking per appointment.

```mermaid
erDiagram
    users {
        int id PK "Auto-increment"
        varchar name "NOT NULL, max 100"
        varchar email UK "NOT NULL, unique, indexed"
        varchar password_hash "NOT NULL, bcrypt"
        varchar phone "Nullable"
        varchar role "NOT NULL, default: customer"
        datetime created_at "NOT NULL, default: utcnow"
    }

    barbers {
        int id PK "Auto-increment"
        varchar name "NOT NULL, max 100"
        varchar specialization "Nullable"
        varchar phone "Nullable"
        varchar status "NOT NULL, default: available"
        datetime created_at "NOT NULL, default: utcnow"
    }

    services {
        int id PK "Auto-increment"
        varchar name "NOT NULL, max 100"
        text description "Nullable"
        int duration "NOT NULL, minutes"
        decimal price "NOT NULL, numeric(10,2)"
        varchar status "NOT NULL, default: active"
        datetime created_at "NOT NULL, default: utcnow"
    }

    appointments {
        int id PK "Auto-increment"
        int user_id FK "NOT NULL, FK -> users.id"
        int barber_id FK "NOT NULL, FK -> barbers.id"
        int service_id FK "NOT NULL, FK -> services.id"
        date appointment_date "NOT NULL"
        time appointment_time "NOT NULL"
        varchar status "NOT NULL, default: booked"
        int queue_number "Nullable, per-day sequence"
        datetime created_at "NOT NULL, default: utcnow"
        datetime updated_at "NOT NULL, auto-updated"
    }

    queue {
        int id PK "Auto-increment"
        int appointment_id FK "NOT NULL, unique, FK -> appointments.id"
        int queue_number "NOT NULL, mirror of appointment"
        int estimated_wait_time "Nullable, minutes"
        varchar status "NOT NULL, default: waiting"
        datetime created_at "NOT NULL, default: utcnow"
        datetime updated_at "NOT NULL, auto-updated"
    }

    users ||--o{ appointments : "books (1:N)"
    barbers ||--o{ appointments : "serves (1:N)"
    services ||--o{ appointments : "provides (1:N)"
    appointments ||--o| queue : "has (1:0..1)"

    appointments }o--|| users : "belongs_to"
    appointments }o--|| barbers : "assigned_to"
    appointments }o--|| services : "uses"
    queue }o--|| appointments : "tracks"
```

### Table Summary

| Table | Columns | PK | FKs | Unique Constraints |
| --- | --- | --- | --- | --- |
| `users` | id, name, email, password_hash, phone, role, created_at | id | — | email |
| `barbers` | id, name, specialization, phone, status, created_at | id | — | — |
| `services` | id, name, description, duration, price, status, created_at | id | — | — |
| `appointments` | id, user_id, barber_id, service_id, appointment_date, appointment_time, status, queue_number, created_at, updated_at | id | user_id→users, barber_id→barbers, service_id→services | (barber_id, appointment_date, appointment_time) |
| `queue` | id, appointment_id, queue_number, estimated_wait_time, status, created_at, updated_at | id | appointment_id→appointments | appointment_id |

### Foreign Key Relationships

| Parent | Child | FK Column | On Delete |
| --- | --- | --- | --- |
| `users` | `appointments` | `user_id` | CASCADE |
| `barbers` | `appointments` | `barber_id` | CASCADE |
| `services` | `appointments` | `service_id` | CASCADE |
| `appointments` | `queue` | `appointment_id` | CASCADE |

### Status Enums

| Table | Column | Allowed Values |
| --- | --- | --- |
| `users` | `role` | customer, admin, staff |
| `barbers` | `status` | available, busy, inactive |
| `services` | `status` | active, inactive |
| `appointments` | `status` | booked, waiting, serving, completed, cancelled, no_show |
| `queue` | `status` | waiting, serving, completed |

---

## 3. Booking flow

```mermaid
sequenceDiagram
    autonumber
    participant C as Customer
    participant F as Frontend (Book page)
    participant A as FastAPI appointments router
    participant Q as QueueEntry
    participant DB as Database

    C->>F: choose service, barber, date, time
    F->>A: POST /api/v1/appointments
    A->>DB: barber active? service active?
    A->>DB: check slot not already booked (not cancelled/no-show)
    alt slot taken
        DB-->>A: existing row
        A-->>F: 409 Conflict "slot just booked"
    else slot free
        A->>DB: next queue_number for the day
        A->>DB: INSERT appointment
        A->>DB: INSERT queue entry (waiting)
        DB-->>A: appointment
        A-->>F: 201 + AppointmentResponse
        F-->>C: redirect to /queue
    end
```

---

## 4. Queue lifecycle (admin view)

```mermaid
stateDiagram-v2
    [*] --> booked : appointment created
    booked --> waiting : queue entry created
    waiting --> serving : POST /queue/{id}/serve
    serving --> completed : POST /queue/{id}/complete
    serving --> waiting : revert
    booked --> cancelled : customer cancels
    booked --> no_show : staff marks
    cancelled --> [*]
    no_show --> [*]
    completed --> [*]
```

---

## 5. Auth flow

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant F as Frontend
    participant A as FastAPI auth router
    participant DB as Database

    U->>F: enter credentials
    F->>A: POST /api/v1/auth/login
    A->>DB: find user by email
    Note over A: verify bcrypt hash
    A-->>F: access_token + user (JWT)
    F->>F: store token & user in localStorage
    F->>A: GET /api/v1/auth/me (Bearer token)
    A->>A: decode JWT -> load user
    A-->>F: user profile
```