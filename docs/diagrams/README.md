# SmartQueue — Diagrams

This folder contains the rendered diagrams (PNG), their editable sources (`.drawio` / `.dbml`), and the Mermaid sources below as text fallbacks. Open the `.drawio` files in <https://app.diagrams.net> and the `.dbml` file in <https://dbdiagram.io>.

| Diagram | PNG | Editable source |
| --- | --- | --- |
| System architecture | [SmartQueueArchi.png](./SmartQueueArchi.png) | [SmartQueueArchi.drawio](./SmartQueueArchi.drawio) |
| Entity Relationship | [SmartQueueER.png](./SmartQueueER.png) | [SmartQueueER.dbml](./SmartQueueER.dbml) |
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

```mermaid
erDiagram
    users {
        int id PK
        string name
        string email UK
        string password_hash
        string phone
        string role
        datetime created_at
    }
    barbers {
        int id PK
        string name
        string specialization
        string phone
        string status
        datetime created_at
    }
    services {
        int id PK
        string name
        string description
        int duration
        numeric price
        string status
        datetime created_at
    }
    appointments {
        int id PK
        int user_id FK
        int barber_id FK
        int service_id FK
        date appointment_date
        time appointment_time
        string status
        int queue_number
        datetime created_at
        datetime updated_at
        unique (barber_id, appointment_date, appointment_time)
    }
    queue {
        int id PK
        int appointment_id FK, UK
        int queue_number
        int estimated_wait_time
        string status
        datetime created_at
        datetime updated_at
    }

    users ||--o{ appointments : books
    barbers ||--o{ appointments : serves
    services ||--o{ appointments : provides
    appointments ||--o| queue : has
```

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