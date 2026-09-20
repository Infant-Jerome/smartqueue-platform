"""Application settings (Pydantic Settings, env-driven).

Env keys:
  DATABASE_URL      Full SQLAlchemy URL, takes precedence when set.
                    Supports: postgresql+psycopg2 / postgresql+psycopg /
                    mysql+pymysql / sqlite. Bare ``postgres://`` and
                    ``postgresql://`` are normalized to
                    ``postgresql+psycopg2://``; bare ``mysql://`` to
                    ``mysql+pymysql://``.
  DATABASE_TYPE/HOST/PORT/USER/PASSWORD/NAME
                    Fallback field-based config (used when DATABASE_URL empty).
                    SQLite is local/test fallback only.
  JWT_SECRET_KEY    Required in production; never log it.
  JWT_ALGORITHM / JWT_EXPIRE_MINUTES
  DEBUG             Env-controlled (true/false/1/0).
  CORS_ORIGINS      Comma-separated list, e.g.
                    "http://localhost:5173,http://localhost:3000".
  APP_NAME / APP_VERSION

``.env`` is for local dev only and must never be committed (see .gitignore).
"""
from functools import lru_cache
import os
import warnings

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _normalize_database_url(url: str) -> str:
    """Normalize common URL shorthands to explicit SQLAlchemy driver URLs.

    Explicit driver URLs (``postgresql+psycopg2://``,
    ``postgresql+psycopg://``, ``mysql+pymysql://``, ``sqlite:///``) pass
    through unchanged. Bare ``postgres://`` / ``postgresql://`` (exactly what
    managed providers such as Render supply) default to
    ``postgresql+psycopg2://`` because ``psycopg2-binary`` is the declared
    production driver (see requirements.txt); bare ``mysql://`` to
    ``mysql+pymysql://``.
    """
    u = url.strip()
    if u.startswith("postgres://"):
        return "postgresql+psycopg2://" + u[len("postgres://"):]
    if u.startswith("postgresql://"):
        # Bare scheme without driver -> default to psycopg2, the declared
        # production driver. Explicit ``postgresql+psycopg2://`` /
        # ``postgresql+psycopg://`` never reach this branch (they start
        # with ``postgresql+``).
        return "postgresql+psycopg2://" + u[len("postgresql://"):]
    if u.startswith("mysql://"):
        return "mysql+pymysql://" + u[len("mysql://"):]
    return u


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # Full DB URL override. Stored under a different attribute name with
    # alias="DATABASE_URL" so the env var is managed by Pydantic while the
    # ``DATABASE_URL`` property below stays free to return the *resolved* URL
    # (override or built from parts). This keeps `settings.DATABASE_URL`
    # backwards compatible with existing imports.
    database_url_raw: str = Field(default="", alias="DATABASE_URL")

    DATABASE_TYPE: str = "sqlite"
    DATABASE_HOST: str = "localhost"
    DATABASE_PORT: int = 3306
    DATABASE_USER: str = "root"
    DATABASE_PASSWORD: str = ""
    DATABASE_NAME: str = "smartqueue_db"

    JWT_SECRET_KEY: str = "your-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60

    APP_NAME: str = "SmartQueue - Barbershop Platform"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    # --- N1-Core notifications (Phase 5B): NOTIF_* settings only. ---
    # Master switch for event-driven fan-out. Channel sends default to
    # Mock providers (record + success, never real) while {CH}_ENABLED is
    # false. Real stubs stay disabled unless ENABLED + credentials exist.
    NOTIFS_ENABLED: bool = True
    APPROACHING_THRESHOLD: int = 2

    EMAIL_ENABLED: bool = False
    EMAIL_FROM: str = ""
    EMAIL_HOST: str = ""
    EMAIL_PORT: int = 587
    EMAIL_USER: str = ""
    EMAIL_PASS: str = ""

    PUSH_ENABLED: bool = False
    PUSH_FROM: str = ""
    PUSH_HOST: str = ""
    PUSH_PORT: int = 443
    PUSH_USER: str = ""
    PUSH_PASS: str = ""

    SMS_ENABLED: bool = False
    SMS_FROM: str = ""
    SMS_HOST: str = ""
    SMS_PORT: int = 443
    SMS_USER: str = ""
    SMS_PASS: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def DATABASE_URL(self) -> str:
        """Resolved SQLAlchemy database URL (override wins, else built)."""
        raw = (self.database_url_raw or "").strip()
        if raw:
            return _normalize_database_url(raw)
        db_type = (self.DATABASE_TYPE or "sqlite").strip().lower()
        if db_type == "mysql":
            return (
                f"mysql+pymysql://{self.DATABASE_USER}:{self.DATABASE_PASSWORD}"
                f"@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}"
            )
        if db_type in ("psycopg2", "postgresql+psycopg2", "postgres+psycopg2"):
            return (
                f"postgresql+psycopg2://{self.DATABASE_USER}:{self.DATABASE_PASSWORD}"
                f"@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}"
            )
        if db_type in ("postgres", "postgresql", "psycopg", "psycopg2") or "+" in db_type:
            # ``+`` branch covers explicit driver strings such as
            # ``postgresql+psycopg`` passed via DATABASE_TYPE (passed
            # through for explicit opt-in); bare names default to the
            # declared psycopg2 production driver.
            driver = "postgresql+psycopg" if db_type == "postgresql+psycopg" else "postgresql+psycopg2"
            return (
                f"{driver}://{self.DATABASE_USER}:{self.DATABASE_PASSWORD}"
                f"@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}"
            )
        # SQLite local/test fallback only. Absolute path to backend/smartqueue.db
        # so CWD does not matter.
        backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        db_path = os.path.join(backend_dir, "smartqueue.db")
        return f"sqlite:///{db_path}"

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    @property
    def is_debug(self) -> bool:
        return bool(self.DEBUG)


    @property
    def is_production(self) -> bool:
        """True when env explicitly says prod, else fallback to DEBUG=False."""
        for var in ("APP_ENV", "ENVIRONMENT", "ENV"):
            val = os.getenv(var, "").strip().lower()
            if val in ("prod", "production"):
                return True
            if val in ("dev", "development", "local", "test", "testing"):
                return False
        return not bool(self.DEBUG)


def _default_jwt_secret() -> str:
    # Read the field default instead of hardcoding the secret string here,
    # so the guard stays in sync if the default ever changes.
    try:
        return str(Settings.model_fields["JWT_SECRET_KEY"].default)
    except Exception:
        return ""


def warn_if_default_secret_in_production(settings: "Settings | None" = None) -> bool:
    """Startup guard: warn (True) if the default JWT secret is used in prod.

    Never logs the secret itself — only emits a warning. Returns True when a
    warning was emitted so lifespan/startup code can act on it.
    """
    s = settings or get_settings()
    try:
        is_default = s.JWT_SECRET_KEY == _default_jwt_secret()
    except Exception:
        return False
    if is_default and s.is_production:
        warnings.warn(
            "JWT_SECRET_KEY is the default value in a production environment; "
            "set a strong JWT_SECRET_KEY env var.",
            UserWarning,
            stacklevel=2,
        )
        return True
    return False


@lru_cache
def get_settings() -> Settings:
    return Settings()
