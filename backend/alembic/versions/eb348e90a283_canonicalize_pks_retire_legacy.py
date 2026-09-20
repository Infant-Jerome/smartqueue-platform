"""canonicalize PKs retire legacy

Revision ID: eb348e90a283
Revises: f7ad2ddb6a36
Create Date: 2026-09-18 20:01:55.744984

Hand-reviewed corrective migration (SQLite-first, deterministic):

- Retires legacy ``id`` PKs in favour of canonical PKs (users.user_id,
  barbers.barber_id, services.service_id, appointments.appointment_id,
  queue.queue_id) and legacy column names (barbers.status ->
  availability_status, services.name -> service_name,
  services.duration -> duration_minutes, appointments.user_id ->
  customer_id, appointments.appointment_time -> start_time/end_time,
  queue.queue_number -> queue_position, queue.estimated_wait_time ->
  estimated_wait_minutes, queue.created_at -> joined_at).
- Creates barber_availability + appointment_status_history.
- Adds appointments.salon_id/booking_type, queue.salon_id/barber_id.
- Retargets every FK to its canonical target with DETERMINISTIC names
  (``fk_<table>_<col>_<referred>``). Raw autogenerate emitted
  ``create_foreign_key(None, ...)`` / ``drop_constraint(None, ...)`` which
  SQLite batch mode rejects ("Constraint must have a name"), and used
  add/drop-column alters that cannot swap PKs on SQLite, so tables are
  recreated instead: rename legacy -> create canonical -> INSERT..SELECT
  copy -> drop legacy. On CLEAN (empty) DBs the copies are no-ops; on
  non-empty DBs ids are preserved and new NOT NULL columns get sensible
  values (booking_type='online', end_time=start+30min, queue barber via
  join, etc.).
- All indexes from canonical metadata are created explicitly (both the
  hand-named ``ix_*`` indexes AND the ``index=True`` auto indexes such as
  ``ix_appointments_customer_id``) so ``alembic check`` reports no drift.
- No ``batch_op.f()``: every name is a plain string (deterministic).
- No server defaults (models use Python-side defaults only).
- Downgrade recreates the exact f7ad2ddb6a36 schema (legacy columns,
  uq_barber_slot, legacy indexes) with deterministic FK names and copies
  data back best-effort.
- PostgreSQL safety (deploy fix): SQLite runs with PRAGMA foreign_keys=OFF,
  but PostgreSQL enforces FKs always and follows them across RENAME by OID,
  so dropping a renamed legacy parent fails with DependentObjectsStillExist
  unless the child's inherited FK is dropped first (explicit ALTER TABLE ..
  DROP CONSTRAINT IF EXISTS, no CASCADE). end_time backfill uses INTERVAL
  on PostgreSQL (no time() function there). Downgrade mirrors the same
  ordering for its *_canonical drops.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'eb348e90a283'
down_revision: Union[str, None] = 'f7ad2ddb6a36'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _pragma_off() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute("PRAGMA foreign_keys=OFF")


def _pragma_on() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute("PRAGMA foreign_keys=ON")


def _drop_fk(table: str, *names: str) -> None:
    """Explicitly drop FK constraint(s) before their legacy parent is dropped.

    SQLite runs this migration with ``PRAGMA foreign_keys=OFF``, so this is
    a no-op there. PostgreSQL enforces FKs at all times AND follows
    dependencies across ``RENAME`` by OID: after ``users`` becomes
    ``users_legacy``, the child's inherited FK still references it, so
    ``DROP TABLE users_legacy`` fails with DependentObjectsStillExist
    unless the FK goes first. The canonical tables rebuilt afterwards
    re-create the canonical FKs (``barbers.user_id -> users.user_id`` etc),
    so nothing required is lost. ``IF EXISTS`` keeps this idempotent and
    tolerant of naming variance; no ``CASCADE`` is used anywhere.
    """
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return
    for name in names:
        op.execute(sa.text(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{name}"'))


def upgrade() -> None:
    _pragma_off()

    # NOTE: new tables are created LAST. SQLite's RENAME rewrites FK
    # references in other tables, so anything created before the
    # rename park below would end up pointing at *_legacy names.
    # --- 2. Park children (FK-safe rework; PRAGMA OFF on sqlite) -----------
    op.rename_table('queue', 'queue_legacy')
    op.rename_table('appointments', 'appointments_legacy')

    # --- 3a. users: id -> user_id ------------------------------------------
    # NOTE: indexes travel with RENAME on sqlite, so drop legacy indexes
    # before parking the table (they are recreated on the canonical table).
    op.drop_index('ix_users_email', table_name='users')
    op.rename_table('users', 'users_legacy')
    op.create_table(
        'users',
        sa.Column('user_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('phone', sa.String(length=20), nullable=True),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('user_id'),
    )
    op.create_index('ix_users_email', 'users', ['email'], unique=True)
    op.execute(
        'INSERT INTO users (user_id, name, email, password_hash, phone, role, created_at, updated_at) '
        'SELECT id, name, email, password_hash, phone, role, created_at, updated_at FROM users_legacy'
    )
    # PG: barbers.user_id (f7 FK, follows the rename) and
    # appointments_legacy.user_id (ebc auto FK) still reference users_legacy.
    # Both tables are rebuilt with canonical FKs below; drop these first.
    _drop_fk('barbers', 'fk_barbers_user_id_users', 'fk_barbers_user_id_users_legacy')
    _drop_fk('appointments_legacy', 'appointments_user_id_fkey')
    op.drop_table('users_legacy')

    # --- 3b. barbers: id -> barber_id, status -> availability_status -------
    op.drop_index('ix_barbers_user_id', table_name='barbers')
    op.drop_index('ix_barbers_salon_id', table_name='barbers')
    op.rename_table('barbers', 'barbers_legacy')
    op.create_table(
        'barbers',
        sa.Column('barber_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('salon_id', sa.Integer(), nullable=True),
        sa.Column('experience_years', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('specialization', sa.String(length=255), nullable=True),
        sa.Column('phone', sa.String(length=20), nullable=True),
        sa.Column('availability_status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint('experience_years >= 0', name='ck_barbers_experience_non_negative'),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.user_id'],
            name='fk_barbers_user_id_users', ondelete='SET NULL'),
        sa.ForeignKeyConstraint(
            ['salon_id'], ['salons.salon_id'],
            name='fk_barbers_salon_id_salons', ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('barber_id'),
    )
    op.create_index('ix_barbers_user_id', 'barbers', ['user_id'], unique=False)
    op.create_index('ix_barbers_salon_id', 'barbers', ['salon_id'], unique=False)
    op.execute(
        'INSERT INTO barbers (barber_id, user_id, salon_id, experience_years, name, specialization, phone, '
        'availability_status, created_at, updated_at) '
        'SELECT id, user_id, salon_id, experience_years, name, specialization, phone, status, created_at, updated_at '
        'FROM barbers_legacy'
    )
    # PG: appointments_legacy.barber_id (ebc auto FK) still references
    # barbers_legacy; it is dropped with appointments_legacy below.
    _drop_fk('appointments_legacy', 'appointments_barber_id_fkey')
    op.drop_table('barbers_legacy')

    # --- 3c. services: id -> service_id, name -> service_name, etc --------
    op.drop_index('ix_services_salon_id', table_name='services')
    op.rename_table('services', 'services_legacy')
    op.create_table(
        'services',
        sa.Column('service_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('salon_id', sa.Integer(), nullable=True),
        sa.Column('service_name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('duration_minutes', sa.Integer(), nullable=False),
        sa.Column('price', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint('duration_minutes > 0', name='ck_services_duration_positive'),
        sa.CheckConstraint('price >= 0', name='ck_services_price_non_negative'),
        sa.ForeignKeyConstraint(
            ['salon_id'], ['salons.salon_id'],
            name='fk_services_salon_id_salons', ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('service_id'),
    )
    op.create_index('ix_services_salon_id', 'services', ['salon_id'], unique=False)
    op.execute(
        'INSERT INTO services (service_id, salon_id, service_name, description, duration_minutes, price, status, '
        'created_at, updated_at) '
        'SELECT id, salon_id, name, description, duration, price, status, created_at, updated_at FROM services_legacy'
    )
    # PG: appointments_legacy.service_id (ebc auto FK) still references
    # services_legacy; it is dropped with appointments_legacy below.
    _drop_fk('appointments_legacy', 'appointments_service_id_fkey')
    op.drop_table('services_legacy')

    # --- 4. appointments: full canonical rework ----------------------------
    op.create_table(
        'appointments',
        sa.Column('appointment_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('salon_id', sa.Integer(), nullable=True),
        sa.Column('barber_id', sa.Integer(), nullable=False),
        sa.Column('service_id', sa.Integer(), nullable=False),
        sa.Column('appointment_date', sa.Date(), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('end_time', sa.Time(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('booking_type', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint('start_time < end_time', name='ck_appointment_time_range'),
        sa.ForeignKeyConstraint(
            ['customer_id'], ['users.user_id'],
            name='fk_appointments_customer_id_users', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['salon_id'], ['salons.salon_id'],
            name='fk_appointments_salon_id_salons', ondelete='SET NULL'),
        sa.ForeignKeyConstraint(
            ['barber_id'], ['barbers.barber_id'],
            name='fk_appointments_barber_id_barbers', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['service_id'], ['services.service_id'],
            name='fk_appointments_service_id_services', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('appointment_id'),
    )
    op.create_index('ix_appointment_customer', 'appointments', ['customer_id'], unique=False)
    op.create_index('ix_appointment_salon', 'appointments', ['salon_id'], unique=False)
    op.create_index('ix_appointment_barber', 'appointments', ['barber_id'], unique=False)
    op.create_index('ix_appointment_service', 'appointments', ['service_id'], unique=False)
    op.create_index('ix_appointment_barber_date', 'appointments', ['barber_id', 'appointment_date'], unique=False)
    op.create_index('ix_appointment_status', 'appointments', ['status'], unique=False)
    op.create_index('ix_appointments_customer_id', 'appointments', ['customer_id'], unique=False)
    op.create_index('ix_appointments_salon_id', 'appointments', ['salon_id'], unique=False)
    op.create_index('ix_appointments_barber_id', 'appointments', ['barber_id'], unique=False)
    op.create_index('ix_appointments_service_id', 'appointments', ['service_id'], unique=False)
    # end_time derivation is dialect-specific: SQLite has no INTERVAL
    # arithmetic (uses time()+modifier), PostgreSQL has no time() function.
    # On clean DBs this copy is a no-op; on data DBs both yield start+30min.
    _end_expr = (
        "time(appointment_time, '+30 minutes')"
        if op.get_bind().dialect.name == "sqlite"
        else "appointment_time + INTERVAL '30 minutes'"
    )
    op.execute(
        "INSERT INTO appointments (appointment_id, customer_id, salon_id, barber_id, service_id, appointment_date, "
        f"start_time, end_time, status, booking_type, created_at, updated_at) "
        "SELECT id, user_id, NULL, barber_id, service_id, appointment_date, appointment_time, "
        f"{_end_expr}, status, 'online', created_at, updated_at FROM appointments_legacy"
    )

    # --- 5. queue: full canonical rework -----------------------------------
    op.create_table(
        'queue',
        sa.Column('queue_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('appointment_id', sa.Integer(), nullable=False),
        sa.Column('salon_id', sa.Integer(), nullable=True),
        sa.Column('barber_id', sa.Integer(), nullable=False),
        sa.Column('queue_position', sa.Integer(), nullable=False),
        sa.Column('joined_at', sa.DateTime(), nullable=False),
        sa.Column('estimated_wait_minutes', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint('queue_position >= 1', name='ck_queue_position_positive'),
        sa.ForeignKeyConstraint(
            ['appointment_id'], ['appointments.appointment_id'],
            name='fk_queue_appointment_id_appointments', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['salon_id'], ['salons.salon_id'],
            name='fk_queue_salon_id_salons', ondelete='SET NULL'),
        sa.ForeignKeyConstraint(
            ['barber_id'], ['barbers.barber_id'],
            name='fk_queue_barber_id_barbers', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('queue_id'),
        sa.UniqueConstraint('appointment_id'),
    )
    op.create_index('ix_queue_appointment_id', 'queue', ['appointment_id'], unique=True)
    op.create_index('ix_queue_salon', 'queue', ['salon_id'], unique=False)
    op.create_index('ix_queue_salon_id', 'queue', ['salon_id'], unique=False)
    op.create_index('ix_queue_barber', 'queue', ['barber_id'], unique=False)
    op.create_index('ix_queue_barber_id', 'queue', ['barber_id'], unique=False)
    op.create_index('ix_queue_position', 'queue', ['queue_position'], unique=False)
    op.create_index('ix_queue_status', 'queue', ['status'], unique=False)
    op.create_index('ix_queue_status_position', 'queue', ['status', 'queue_position'], unique=False)
    op.execute(
        'INSERT INTO queue (queue_id, appointment_id, salon_id, barber_id, queue_position, joined_at, '
        'estimated_wait_minutes, status, updated_at) '
        'SELECT q.id, q.appointment_id, NULL, a.barber_id, q.queue_number, q.created_at, q.estimated_wait_time, '
        'q.status, q.updated_at FROM queue_legacy q JOIN appointments_legacy a ON a.id = q.appointment_id'
    )
    op.drop_table('queue_legacy')
    op.drop_table('appointments_legacy')

    # --- 6. New tables (canonical, named FKs + all indexes) ----------------
    # Created last so no later RENAME rewrites their FK targets.
    op.create_table(
        'barber_availability',
        sa.Column('availability_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('barber_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('end_time', sa.Time(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint('start_time < end_time', name='ck_availability_time_range'),
        sa.ForeignKeyConstraint(
            ['barber_id'], ['barbers.barber_id'],
            name='fk_availability_barber_id_barbers', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('availability_id'),
    )
    op.create_index('ix_availability_barber_date', 'barber_availability', ['barber_id', 'date'], unique=False)
    op.create_index('ix_barber_availability_barber_id', 'barber_availability', ['barber_id'], unique=False)

    op.create_table(
        'appointment_status_history',
        sa.Column('history_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('appointment_id', sa.Integer(), nullable=False),
        sa.Column('old_status', sa.String(length=20), nullable=True),
        sa.Column('new_status', sa.String(length=20), nullable=False),
        sa.Column('changed_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['appointment_id'], ['appointments.appointment_id'],
            name='fk_status_history_appointment_id_appointments', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('history_id'),
    )
    op.create_index('ix_appointment_status_history_appointment_id', 'appointment_status_history', ['appointment_id'], unique=False)
    op.create_index('ix_status_history_appointment', 'appointment_status_history', ['appointment_id'], unique=False)
    op.create_index('ix_status_history_changed_at', 'appointment_status_history', ['changed_at'], unique=False)

    _pragma_on()


def downgrade() -> None:
    _pragma_off()

    # --- 1. Drop the two Phase-1.1 tables ----------------------------------
    op.drop_index('ix_status_history_changed_at', table_name='appointment_status_history')
    op.drop_index('ix_status_history_appointment', table_name='appointment_status_history')
    op.drop_index('ix_appointment_status_history_appointment_id', table_name='appointment_status_history')
    op.drop_table('appointment_status_history')
    op.drop_index('ix_barber_availability_barber_id', table_name='barber_availability')
    op.drop_index('ix_availability_barber_date', table_name='barber_availability')
    op.drop_table('barber_availability')

    # --- 2. Park canonical children ----------------------------------------
    op.rename_table('queue', 'queue_canonical')
    op.rename_table('appointments', 'appointments_canonical')

    # --- 3a. users back to legacy ------------------------------------------
    # NOTE: indexes travel with RENAME on sqlite; drop canonical ones first.
    op.drop_index('ix_users_email', table_name='users')
    op.rename_table('users', 'users_canonical')
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('phone', sa.String(length=20), nullable=True),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_users_email', 'users', ['email'], unique=True)
    op.execute(
        'INSERT INTO users (id, name, email, password_hash, phone, role, created_at, updated_at) '
        'SELECT user_id, name, email, password_hash, phone, role, created_at, updated_at FROM users_canonical'
    )
    # PG mirror of the upgrade fix: the renamed canonical children still
    # reference users_canonical; both are rebuilt/dropped below.
    _drop_fk('barbers_canonical', 'fk_barbers_user_id_users')
    _drop_fk('appointments_canonical', 'fk_appointments_customer_id_users')
    op.drop_table('users_canonical')

    # --- 3b. barbers back to legacy (f7 state, deterministic FK names) -----
    op.drop_index('ix_barbers_user_id', table_name='barbers')
    op.drop_index('ix_barbers_salon_id', table_name='barbers')
    op.rename_table('barbers', 'barbers_canonical')
    op.create_table(
        'barbers',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('specialization', sa.String(length=255), nullable=True),
        sa.Column('phone', sa.String(length=20), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('salon_id', sa.Integer(), nullable=True),
        sa.Column('experience_years', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.id'],
            name='fk_barbers_user_id_users', ondelete='SET NULL'),
        sa.ForeignKeyConstraint(
            ['salon_id'], ['salons.salon_id'],
            name='fk_barbers_salon_id_salons', ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_barbers_user_id', 'barbers', ['user_id'], unique=False)
    op.create_index('ix_barbers_salon_id', 'barbers', ['salon_id'], unique=False)
    op.execute(
        'INSERT INTO barbers (id, name, specialization, phone, status, created_at, user_id, salon_id, '
        'experience_years, updated_at) '
        'SELECT barber_id, name, specialization, phone, availability_status, created_at, user_id, salon_id, '
        'experience_years, updated_at FROM barbers_canonical'
    )
    _drop_fk('appointments_canonical', 'fk_appointments_barber_id_barbers')
    op.drop_table('barbers_canonical')

    # --- 3c. services back to legacy (f7 state) ----------------------------
    op.drop_index('ix_services_salon_id', table_name='services')
    op.rename_table('services', 'services_canonical')
    op.create_table(
        'services',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('duration', sa.Integer(), nullable=False),
        sa.Column('price', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('salon_id', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['salon_id'], ['salons.salon_id'],
            name='fk_services_salon_id_salons', ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_services_salon_id', 'services', ['salon_id'], unique=False)
    op.execute(
        'INSERT INTO services (id, name, description, duration, price, status, created_at, salon_id, updated_at) '
        'SELECT service_id, service_name, description, duration_minutes, price, status, created_at, salon_id, '
        'updated_at FROM services_canonical'
    )
    _drop_fk('appointments_canonical', 'fk_appointments_service_id_services')
    op.drop_table('services_canonical')

    # --- 4. appointments back to legacy (ebc+f7 state) ---------------------
    op.create_table(
        'appointments',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('barber_id', sa.Integer(), nullable=False),
        sa.Column('service_id', sa.Integer(), nullable=False),
        sa.Column('appointment_date', sa.Date(), nullable=False),
        sa.Column('appointment_time', sa.Time(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('queue_number', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.id'],
            name='fk_appointments_user_id_users', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['barber_id'], ['barbers.id'],
            name='fk_appointments_barber_id_barbers', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['service_id'], ['services.id'],
            name='fk_appointments_service_id_services', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('barber_id', 'appointment_date', 'appointment_time', name='uq_barber_slot'),
    )
    op.execute(
        'INSERT INTO appointments (id, user_id, barber_id, service_id, appointment_date, appointment_time, status, '
        'queue_number, created_at, updated_at) '
        'SELECT appointment_id, customer_id, barber_id, service_id, appointment_date, start_time, status, NULL, '
        'created_at, updated_at FROM appointments_canonical'
    )
    _drop_fk('queue_canonical', 'fk_queue_appointment_id_appointments')
    op.drop_table('appointments_canonical')

    # --- 5. queue back to legacy (ebc state) -------------------------------
    op.create_table(
        'queue',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('appointment_id', sa.Integer(), nullable=False),
        sa.Column('queue_number', sa.Integer(), nullable=False),
        sa.Column('estimated_wait_time', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['appointment_id'], ['appointments.id'],
            name='fk_queue_appointment_id_appointments', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('appointment_id'),
    )
    op.execute(
        'INSERT INTO queue (id, appointment_id, queue_number, estimated_wait_time, status, created_at, updated_at) '
        'SELECT queue_id, appointment_id, queue_position, estimated_wait_minutes, status, joined_at, updated_at '
        'FROM queue_canonical'
    )
    op.drop_table('queue_canonical')

    _pragma_on()
