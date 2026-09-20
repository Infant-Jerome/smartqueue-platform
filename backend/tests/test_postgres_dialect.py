"""PostgreSQL dialect regression (Render deploy fix).

Render supplies bare ``postgres://...`` URLs. The app must normalize them to
``postgresql+psycopg2://`` (the declared production driver in
requirements.txt: ``psycopg2-binary``), never to ``postgresql+psycopg://``
(``psycopg`` v3 is NOT installed -> ModuleNotFoundError at engine creation).

Credentials are never printed: assertions use structural checks on a
placeholder password only.
"""
import pytest

from app.core.config import _normalize_database_url, Settings


def test_bare_postgres_scheme_uses_psycopg2():
    out = _normalize_database_url("postgres://u:pw@host:5432/db")
    assert out == "postgresql+psycopg2://u:pw@host:5432/db"


def test_bare_postgresql_scheme_uses_psycopg2():
    out = _normalize_database_url("postgresql://u:pw@host:5432/db")
    assert out == "postgresql+psycopg2://u:pw@host:5432/db"


def test_explicit_drivers_pass_through():
    assert _normalize_database_url("postgresql+psycopg2://u:pw@h/db").startswith(
        "postgresql+psycopg2://"
    )
    # Explicit v3 opt-in is preserved (operator's responsibility to install it).
    assert _normalize_database_url("postgresql+psycopg://u:pw@h/db").startswith(
        "postgresql+psycopg://"
    )


def test_sqlite_and_mysql_untouched():
    assert _normalize_database_url("sqlite:///./smartqueue.db").startswith("sqlite")
    assert _normalize_database_url("mysql://u:pw@h/db").startswith("mysql+pymysql://")


def test_settings_resolves_render_style_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://u:pw@host:5432/db")
    assert Settings().DATABASE_URL == "postgresql+psycopg2://u:pw@host:5432/db"


def test_psycopg2_dialect_importable():
    """The normalized dialect must resolve to the installed driver module."""
    psycopg2 = pytest.importorskip("psycopg2")
    assert psycopg2 is not None
    from sqlalchemy.dialects import registry

    entry = registry.load("postgresql+psycopg2")
    assert "psycopg2" in entry.__module__
