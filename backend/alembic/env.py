"""Alembic environment: resolves DB URL, exposes model metadata, runs migrations.

URL precedence (first non-empty wins):
  1. ``DATABASE_URL`` environment variable (12-factor / Render / tests).
  2. ``app.core.config.get_settings().DATABASE_URL`` (builds from env/file config).
  3. ``alembic.ini`` ``sqlalchemy.url`` fallback (never crash if 1-2 unavailable).

Metadata discovery:
  - Canonical Base lives at ``app.db.base`` (single source of truth).
  - ``import app.models`` eagerly registers all 8 canonical tables
    (users.user_id, salons.salon_id, barbers.barber_id,
    services.service_id, barber_availability.availability_id,
    appointments.appointment_id, queue.queue_id,
    appointment_status_history.history_id) on ``Base.metadata``.
    ``target_metadata`` is exactly that canonical metadata.

SQLite vs Postgres:
  - SQLite: ``render_as_batch=True`` (ALTER support), NullPool via
    ``engine_from_config`` default is fine; file path comes from URL.
  - Postgres (``postgresql://`` / ``postgresql+psycopg2://``): plain configure;
    ``compare_type=True`` catches type drift on both backends.
"""
from logging.config import fileConfig
import os
import sys

from sqlalchemy import engine_from_config, pool
from alembic import context

# Ensure backend/ root (parent of alembic/) is importable regardless of CWD.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def resolve_database_url() -> str | None:
    """Return effective SQLAlchemy URL following the precedence above."""
    env_url = os.getenv("DATABASE_URL")
    if env_url and env_url.strip():
        return env_url.strip()
    try:
        from app.core.config import get_settings

        settings_url = get_settings().DATABASE_URL
        if settings_url and str(settings_url).strip():
            return str(settings_url).strip()
    except Exception:
        pass
    ini_url = config.get_main_option("sqlalchemy.url")
    if ini_url and ini_url.strip():
        return ini_url.strip()
    return None


DATABASE_URL = resolve_database_url()
# Normalize bare provider schemes (e.g. Render's ``postgres://``) to the
# declared psycopg2 dialect; SQLAlchemy has no bare ``postgres`` dialect and
# ``psycopg`` (v3) is not installed. Never log the URL (credentials).
if DATABASE_URL and not DATABASE_URL.startswith("sqlite"):
    try:
        from app.core.config import _normalize_database_url

        DATABASE_URL = _normalize_database_url(DATABASE_URL)
    except Exception:
        pass
if DATABASE_URL:
    config.set_main_option("sqlalchemy.url", DATABASE_URL)

# --- Metadata discovery: canonical Base + all 8 models -------------------
from app.db.base import Base  # noqa: E402  (canonical Base, single source of truth)

import app.models  # noqa: E402,F401  (eager: registers all 8 tables on Base.metadata)
from app.models import (  # noqa: E402,F401  (explicit for autogenerate)
    Appointment,
    AppointmentStatusHistory,
    Barber,
    BarberAvailability,
    Queue,
    Salon,
    Service,
    User,
)

target_metadata = Base.metadata

_IS_SQLITE = (DATABASE_URL or "").startswith("sqlite")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a live connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
        render_as_batch=_IS_SQLITE,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (live engine connection)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            render_as_batch=_IS_SQLITE,
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
