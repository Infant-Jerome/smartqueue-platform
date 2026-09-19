"""Backwards-compatibility shim: canonical implementation lives in app.db.*.

All existing imports (``app.main``, ``app.models``, ``app.api``,
``alembic/env.py``, ``seed.py``, ``tests/conftest.py``) keep working.
New code should import from ``app.db.database`` / ``app.db.base`` directly.
Single ``Base`` is defined in ``app.db.base`` — never redefined here.
"""
from app.db.base import Base
from app.db.database import SessionLocal, create_tables, dispose_engine, engine, get_db

__all__ = ["Base", "engine", "SessionLocal", "get_db", "create_tables", "dispose_engine"]
