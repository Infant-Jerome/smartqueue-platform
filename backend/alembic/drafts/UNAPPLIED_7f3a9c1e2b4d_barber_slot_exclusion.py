"""UNAPPLIED / UNVERIFIED DRAFT -- DO NOT MOVE INTO alembic/versions/.

Same-slot booking race: Postgres exclusion-constraint backstop.

Status: PREPARED ONLY. Never applied, never tested -- no PostgreSQL with
known credentials exists in this environment (server answers on
127.0.0.1:5432 but authentication fails; system test interpreter has no
psycopg2 driver). Moving this file into alembic/versions/ or applying it
without first passing tests/test_booking_race_pg.py (10 threads,
exactly 1x201 + 9x409, zero duplicate rows) on a real PostgreSQL is
forbidden; see docs/booking-race-pg-verification.md for the exact steps.

Design (reviewed, not executed):
* Requires btree_gist (bundled with stock Postgres, CREATE EXTENSION).
* Expression tsrange((appointment_date + start_time),
  (appointment_date + end_time)): date + time -> timestamp is IMMUTABLE,
  tsrange() over constants is IMMUTABLE, so it is indexable.
* Partial predicate `status NOT IN ('cancelled', 'no_show')` mirrors the
  app's _IGNORED_OVERLAP_STATUSES exactly: terminal rows never block.
* Covers the BARBER-side race only. The customer-side overlap (same
  customer, different barber) stays an application-level check -- a second
  partial exclusion on customer_id was deliberately NOT added (wider lock
  surface, more false-positive risk under reschedules).
* Primary race guard is the transaction-scoped advisory lock in
  app/services/appointments_service.py::acquire_barber_day_lock (no schema
  change, no-op on SQLite). This constraint is the backstop: any leak
  surfaces as IntegrityError, which both write paths already map to 409.

When verified: move into alembic/versions/ (down_revision = 'd4e5f6a7b8c9',
the current head at the time of drafting), run `alembic upgrade head`
against staging Postgres, then run the concurrency test.

Revision ID: 7f3a9c1e2b4d
Revises: d4e5f6a7b8c9
Create Date: 2026-10-10 (draft)
"""

from typing import Sequence, Union

from alembic import op

revision: str = "7f3a9c1e2b4d"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # Draft is Postgres-only; never touch SQLite/MySQL chains.
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        """
        ALTER TABLE appointments
        ADD CONSTRAINT uq_appointments_barber_slot
        EXCLUDE USING gist (
            barber_id WITH =,
            tsrange(
                (appointment_date + start_time),
                (appointment_date + end_time)
            ) WITH &&
        )
        WHERE (status NOT IN ('cancelled', 'no_show'))
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        "ALTER TABLE appointments DROP CONSTRAINT IF EXISTS "
        "uq_appointments_barber_slot"
    )
