# SmartQueue — Phase 12 Performance & Load Testing

## 1. Objective

Determine whether SmartQueue remains responsive and correct under realistic
concurrent usage. Measure first; fix only evidence-based bottlenecks. No UI,
auth, RBAC, booking, queue, SAWTE, WS, schema, migration, or API-contract
changes were made in this phase (zero code changes).

## 2. Testing Environment

- **Load env (isolated, local):** `uvicorn app.main:app` on
  `http://127.0.0.1:8123`, single worker, file SQLite
  (`phase12/loadtest.db`, temp dir, never production), `DEBUG=False`.
  Seeded: 1 salon (09:00–18:00), 3 barbers, 2 services (30/20 min),
  availability 09:00–18:00 on TEST_DATE=2026-09-28, 60 customers + admin /
  staff / barber users. All load traffic stayed on localhost.
- **Production:** only 2 read-only smoke requests total
  (`GET /api/health`, `GET /` Vercel). No production load testing
  (Render free-tier safety + no prod-data risk). Prod load behavior is
  therefore NOT measured — stated as limitation, not claimed.
- **Harness:** `requests` + `ThreadPoolExecutor` (HTTP),
  `websockets` v16 (WS), in-process timing (SAWTE). Per-request timeout 30 s.
- **Caveats:** 10 parallel agents shared one server/DB; SQLite serializes
  writes (lock contention is an env artifact, not prod Postgres behavior);
  agents observed mid-run server wedges/restarts (see §21). Results below
  are the actually measured values.

## 3. Test Methodology

Baseline (1 user) → concurrency ladder (5/10/25/50) per endpoint family →
auth load → booking/race → queue reads/ops → SAWTE timing → WS load →
static DB/resource review → frontend build/lint → full backend suite.
Latency = client-measured wall ms (includes loopback + server). Percentiles
computed per level. 409/400/422 on booking paths = business rejection
(counted separately, never as system failure); 5xx/timeout/conn-refused =
system failure.

## 4. Performance Targets

p50 < 300 ms, p95 < 1000 ms (reads/auth/queue/WS delivery stable);
booking p95 < 1500 ms; race duplicates = 0; WS delivery stable;
frontend build PASS; backend regression green.

## 5. Baseline Results

Sequential, 1 user (agent A1): `GET /api/health` ×5 mean **11.1 ms**;
`GET /api/v1/services` ×10 (authed) mean **10.9 ms**. Local health during
load window: **11.6 ms** (agent A10).

## 6. API Performance

Read mix (30% services / 20% barbers / 20% availability / 15% appointments /
15% queue my-position), 100 req/level, 0 failures at every level:

| Concurrency | p50 | p90 | p95 | p99 | min | max | Throughput |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 5 | 42.3 | 58.9 | 64.5 | 71.2 | 17.1 | 82.3 | 112 req/s |
| 10 | 92.1 | 112.1 | 115.1 | 124.3 | 53.8 | 126.4 | 104 req/s |
| 25 | 194.7 | 266.4 | 268.1 | 278.0 | 10.2 | 281.9 | 113 req/s |
| 50 | 321.9 | 432.1 | 437.6 | 440.4 | 46.6 | 450.6 | 123 req/s |

All ms. p95 < 1000 ms at every level up to 50. Throughput flat
(~104–123 req/s, single-worker loopback). No 100-concurrency read run
(completed within time budget at 50; 100 NOT TESTED).

## 7. Authentication Load

`POST /api/v1/auth/login` (valid creds only; the shared Phase-11 limiter
counts 401s — zero invalid attempts sent, zero 401/429 seen):

| Concurrency | req | ok | p50 | p95 | max | Throughput |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 5 | 5 | 403.7 | 423.4 | 426.5 | 2.5 req/s |
| 10 | 10 | 10 | 675.1 | 705.4 | 709.3 | 13.7 req/s |
| 25 | 25 | 25 | 1175.7 | **1577.9** | 1593.6 | 15.2 req/s |

`GET /api/v1/auth/me` @25 conc (50 req): p50 193.6 ms, p95 267.9 ms, 0 fail.
Login latency is bcrypt-bound (~400 ms serial floor); p95 < 1000 ms holds
at 1 and 10 conc, **missed at 25 conc (1578 ms)**. No brute-force testing
(Phase 11 scope).

## 8. Appointment Load

Dedicated distinct-slot concurrency run (agent A3) was cancelled
mid-phase → concurrency levels 5/10/25 for booking are **NOT TESTED**.
Measured booking evidence from other agents (same endpoint, same server):
single booking **207 ms** (A7, 201) and **238 ms** (A4, 201); sequential
queue-op bookings all 201. No 5xx on any booking attempt. Past-date
negative → 400 as designed (A3 plan; consistent with unit suite).

## 9. Concurrent Booking Test

10-way barrier-fired same-slot bookings (barber2, 2026-09-28 14:00,
10 distinct users, lat 1223–2175 ms): result **10×201 + 0×409** —
expected 1×201 + 9×409. Staff verification: 10 rows, **9 duplicates**.
The app-level overlap check + UNIQUE `appointment_id` did NOT serialize
this race under local SQLite concurrency (check-then-insert interleave;
service docstring explicitly disclaims hard race-proofing without
`FOR UPDATE`/exclusion — `appointments_service.py:10-20`). Phase 11's
5-thread race passed on production Postgres; this failure is observed on
**local SQLite** and must not be extrapolated to prod Postgres without a
Postgres-level retest. Recorded as open issue PERF-01.

## 10. Queue Performance

Staff/customer queue reads, 0 failures at every level (ms):

| Concurrency | req | p50 | p95 | max | Throughput |
| --- | --- | --- | --- | --- | --- |
| 1 | 10 | 17.2 | 25.7 | 26.2 | 55 req/s |
| 10 | 100 | 82.0 | 107.0 | 111.4 | 116 req/s |
| 25 | 100 | 251.7 | 344.0 | 410.1 | 93 req/s |
| 50 | 100 | 523.5 | 662.7 | 733.5 | 85 req/s |

Positions sorted, no duplicate active (barber, position) in read-only
windows. (After A4's race-writes, barber2 showed 9 waiting rows all at
position 1 — a consequence of the §9 duplicates, not a read bug.)

## 11. Queue Operation Performance

Sequential, staff, isolated to barber2 (ms): serve-next 200 in **731.7**;
serve on serving entry → 400 "already serving" (correct guard, not a
failure); complete 200 in **319.8**; extra booking 201 in 238.4;
skip 200 in **440.6**. Final state consistent (no duplicate serving).
All op latencies < 1000 ms.

## 12. SAWTE Performance

In-process `estimate_wait`, 20 iters/case: (a) empty history + 1 waiting:
mean **3.20 ms** p95 4.07; (b) 5 history + 5 waiting: **3.56 ms** p95 5.64;
(c) 50 history + 20 waiting / 3 services: **6.13 ms** p95 7.85.
Query count case (c): **8/call** = bounded by distinct pairs (no N+1;
fallback `IN` batch verified). Staff `GET /queue` (per-entry confidence
serialization) p95 ~107 ms @10 conc (§10). SAWTE is not a bottleneck.
Formula untouched.

## 13. WebSocket Performance

Native WS `/api/v1/ws/queue/1?token&date=2026-09-28`:
- Connect: 1/1 (100%, 62 ms + 6.9 ms first event); 10/10 (100%,
  avg 82 ms conn / 26 ms first event); **25: 9/25 (36%)** — 16
  first-event timeouts (handshake ok, no initial event in 10 s). Server
  wedged twice under 25-conn WS pressure (HTTP+WS timeouts, self-recovered).
- Delivery (10 held clients): booking broadcast 10/10, req→event avg
  **186.7 ms**; serve broadcast 10/10, avg **362.2 ms**.
- **BUG PERF-02:** 10 copies per client per mutation (expected 1) — each of
  N connections re-broadcasts every publish (N×N fan-out, confirmed with
  2-client diag). Disconnects 10/10 clean. 50/100-conn WS NOT TESTED
  (stopped after 25-conn degradation — do not extrapolate capacity).

## 14. Database Performance

Index inventory verified in models: `ix_appointment_barber_date`
(`appointment.py:76`), customer/barber/service/salon/status indexes,
`ix_queue_status_position` (`queue.py:56`), queue 1:1 via
column-level `unique+index` on `appointment_id` (`queue.py:23-29`),
`ix_availability_barber_date`, status-history indexes, unique user email.
No composite (barber,date,status)/(barber,date,position) covering indexes.
Static observations (no schema change): unbounded `.all()` list paths
(`appointments_service.py:308-320`, `queue_service.py:785`,
`api/v1/appointments.py:310/318/324`, `api/v1/queue.py:130`);
day-scoped overlap checks load day rows + Python loop
(`appointments_service.py:398-424`); route-layer per-entry confidence
calls are N+1-shaped (`queue.py:49-59` vs `130-131`) though cheap per §12.
Single-transaction create with rollback (`447-485`). No slow-query log
available on SQLite; no prod DB metrics accessible.

## 15. Resource Usage

Local uvicorn only: RSS **110–117 MB**, 24–27 threads, ~0% CPU idle between
requests, sys CPU 22–26% during load. Render free-tier metrics not
observable — none claimed.

## 16. Error Rates

Reads (500 req across A1+A5 ladders): 0% system failures. Auth (90 req):
0%. Queue ops: 0% (one 400 was a correct business guard). Race: 0% system
failures, 90% business-incorrect (9 duplicate 201s — correctness, §9). WS:
64% first-event failure at 25 conn (§13). Booking: no 5xx observed.
SQLite "database is locked" never surfaced as 500 in measured runs.

## 17. Bottlenecks

1. **PERF-02 (WS N×N fan-out + 25-conn first-event stalls)** — evidence §13.
2. **PERF-01 (same-slot race duplicates on SQLite concurrency)** —
   evidence §9, Postgres retest required.
3. **Login p95 > 1 s @25 conc (bcrypt-serial)** — evidence §7; expected
   for password hashing,mitigated in practice by token reuse161516.
4. Latency scales ~linearly with concurrency (single worker + bcrypt +
   SQLite) — throughput plateau ~85–123 req/s local; no max capacity claimed.

## 18. Optimizations Applied

**None.** Per policy (measure → justify → fix → re-measure): findings are
recorded with recommendations (WS broadcast dedup/single-publisher;
Postgres exclusion constraint or `FOR UPDATE` for slot race + retest;
login fine as-is — bcrypt cost is a security feature; consider
`limit/offset` on list endpoints only with product sign-off). No code,
schema, contract, or design touched.

## 19. Before vs After

No optimizations → no before/after comparison. Baselines above (§5–§7,
§10) are the reference for future work.

## 20. Regression Testing

- Backend: **273 passed, 1 skipped** (309 s; skip = env-only psycopg2
  import proof). Matches/extends baseline (267 + 6 Phase-11 tests).
- Frontend build: **PASS** (13.9 s; JS 401 KB / gzip 119 KB,
  CSS 37 KB / gzip 7.7 KB — no Phase-9 bloat signal).
- Frontend lint: **PASS**, 1 pre-existing Fast Refresh warning
  (`AuthContext.jsx:96`), untouched.

## 21. Limitations

- No production load testing (2 read-only smoke reqs only:
  prod `/api/health` 200 `database:up` + headers present; Vercel `/` 200).
- Booking distinct-slot concurrency (5/10/25) NOT TESTED (agent
  cancelled); WS 50/100 NOT TESTED; reads at 100 NOT TESTED.
- SQLite ≠ Postgres: §9 race result is env-specific until retested on
  Postgres; lock/pool behavior differs in prod.
- Shared-server parallel-agent interference (wedged episodes, one agent
  restarted the server mid-run, end-of-run server down — since cleaned);
  timings include cross-agent contention; treat p95s as conservative.
- No Render CPU/mem/DB metrics available.

## 22. Final Performance Status

**PASS WITH ISSUES** — responsive and correct for reads/queue/auth at
tested levels (p95 < 1 s to 50 conc reads, 25 conc queue; booking singles
~210–240 ms; SAWTE ~6 ms; zero 5xx), regressions green; but PERF-01
(race duplicates, SQLite-evidenced) and PERF-02 (WS duplicate fan-out +
25-conn degradation) are open, login p95 misses target at 25 conc, and
the booking-concurrency + WS-50/100 + prod-load cells are NOT TESTED.

### Performance test matrix

| ID | Test | Load | Metric | Expected | Actual | Status |
| --- | --- | --- | --- | --- | --- | --- |
| P-01 | API baseline | 1 | p95 | <1 s | ~26 ms | PASS |
| P-02 | Services/reads | 10–50 | p95 | <1 s | 115/268/438 ms | PASS |
| P-03 | Appointments read | 10–50 | p95 | <1 s | in mix, 0 fail | PASS |
| P-04 | Booking | 10 | p95 | <1.5 s | singles ~0.21–0.24 s; conc NOT TESTED | NOT TESTED |
| P-05 | Queue | 25 | p95 | <1 s | 344 ms | PASS |
| P-06 | Concurrent booking | 10 | duplicates | 0 | 9 (SQLite) | FAIL* |
| P-07 | WebSocket | 25 | delivery | stable | 36% conn; 10× dup fan-out | FAIL* |
| P-08 | WebSocket | 50 | delivery | stable | — | NOT TESTED |
| P-09 | SAWTE | controlled | calc | stable | 3–6 ms, 8 q/call | PASS |
| P-10 | API stress | 50 | errors | acceptable | 0% | PASS |
| P-11 | API stress | 100 | errors | acceptable | — | NOT TESTED |
| P-12 | Frontend build | N/A | build | PASS | PASS 13.9 s | PASS |

*FAIL = open issue with evidence (PERF-01/PERF-02); env caveats in §9/§13.
