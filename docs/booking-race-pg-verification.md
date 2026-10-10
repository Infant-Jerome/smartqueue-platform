# Same-slot booking race: remaining PostgreSQL verification steps

Status: **PREPARED ONLY -- race NOT claimed resolved.** Prepared 2026-10-10:
code guards (dialect-gated, safe no-ops on SQLite), an UNAPPLIED draft
migration, and the concurrency acceptance test. Facts established locally:

* Server IS listening on 127.0.0.1:5432 (TCP open; psycopg2 connect gets
  `FATAL: password authentication failed`, proving a live server).
* No working credentials exist in this environment (`DATABASE_URL` unset,
  `.env.example` only); the system test interpreter (3.14) has no psycopg2
  driver (only `backend/.venv` 3.12 does).

## What was prepared (not applied)

1. `app/services/appointments_service.py`
   * `acquire_barber_day_lock()` -- `pg_advisory_xact_lock(barber_id, YYYYMMDD)`
     on PostgreSQL only, no-op elsewhere; called in `create_appointment`
     before the overlap reads.
   * `IntegrityError` -> HTTP 409 mapping around the booking commit.
2. `app/api/v1/appointments.py` (PUT reschedule)
   * Same advisory lock before `_check_slot_conflicts`, `IntegrityError` ->
     409 around the commit. `_apply_cancel` path untouched.
3. `alembic/drafts/UNAPPLIED_7f3a9c1e2b4d_barber_slot_exclusion.py`
   * Draft partial exclusion constraint (btree_gist). Deliberately outside
     `alembic/versions/` so no chain/deploy picks it up.
4. `tests/test_booking_race_pg.py` -- skipped unless `SMARTQUEUE_PG_TEST_URL`
   is set AND reachable.

## Exact verification steps (on a host with real PostgreSQL)

1. Provision a scratch database, e.g.
   `createdb smartqueue_race_test` (dedicated; the test drops tables).
2. Export the URL (credentials never committed/printed):
   `SMARTQUEUE_PG_TEST_URL=postgresql+psycopg2://user:pw@host:5432/smartqueue_race_test`
3. Run the race test with the interpreter that has the driver
   (`backend/.venv`, which pins `psycopg2-binary`):
   `.\.venv\Scripts\python.exe -m pytest tests/test_booking_race_pg.py -v`
   Expect **1 passed** with 1x201 + 9x409 asserted inside.
4. ONLY after step 3 passes: move the draft migration into
   `alembic/versions/`, run `alembic upgrade head` on staging, re-run step 3
   (constraint backstop now active), then run the full regression suite.
5. If step 3 fails: do NOT promote the migration; the advisory-lock path
   and/or the exclusion expression needs revision first.

## Residual scope (by design, document for the coordinator)

* The exclusion draft covers the barber-side race only; the customer-side
  overlap (same customer, two barbers) stays application-level.
* `queue_position` per-day numbering (`max + 1`) has its own benign race
  (duplicate positions possible); no constraint added -- queue engine
  (Phase 4) owns numbering semantics.
