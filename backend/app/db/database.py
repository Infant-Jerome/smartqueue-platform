"""Canonical SQLAlchemy 2.x engine/session wiring.

- Single ``Base`` lives in :mod:`app.db.base` (imported here, never redefined).
- ``engine`` / ``SessionLocal`` are module singletons built from settings.
- ``get_db`` is a FastAPI dependency yielding a request-scoped session:
  no global session is ever shared; it rolls back on error and always closes.
- SQLite (local/test fallback only) gets ``check_same_thread=False``;
  server DBs get ``pool_pre_ping`` + ``pool_recycle`` for clean lifecycle.
- Never log the URL (it may contain credentials).
"""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.base import Base

settings = get_settings()

_db_url = settings.DATABASE_URL
if _db_url.startswith("sqlite"):
    engine = create_engine(
        _db_url,
        echo=settings.DEBUG,
        connect_args={"check_same_thread": False},
    )
else:
    engine = create_engine(
        _db_url,
        pool_pre_ping=True,
        pool_recycle=3600,
        echo=settings.DEBUG,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Yield a request-scoped session; rollback on error, always close."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def create_tables() -> None:
    """Create all tables (used by lifespan + seed; migrations own prod DDL)."""
    Base.metadata.create_all(bind=engine)


def dispose_engine() -> None:
    """Dispose pooled connections (tests / shutdown hooks)."""
    engine.dispose()
