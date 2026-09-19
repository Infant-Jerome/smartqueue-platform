"""Single declarative Base for all models.

Import Base ONLY from here (canonical) or via the ``app.core.database``
compatibility shim. Defining another ``DeclarativeBase`` subclass elsewhere
will split metadata and break Alembic/tests.
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
