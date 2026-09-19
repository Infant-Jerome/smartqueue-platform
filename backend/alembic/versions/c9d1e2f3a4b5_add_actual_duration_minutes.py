"""add appointments.actual_duration_minutes (SAWTE Phase 5C)

Revision ID: c9d1e2f3a4b5
Revises: a91f3c7e2b44
Create Date: 2026-09-19

SAWTE measured-duration column only (smallest justified change):
- Adds nullable ``appointments.actual_duration_minutes`` (Integer, NULL).
- No default, no CHECK, no index: mirrors the model metadata exactly so
  ``alembic check`` reports no drift. NULL = unknown (estimator falls back
  to Service.duration_minutes). S2 will write it on complete via
  ``services.sawte.compute_actual_minutes``.
- SQLite-safe via batch_alter_table. Downgrade drops the column.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'c9d1e2f3a4b5'
down_revision: Union[str, None] = 'a91f3c7e2b44'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('appointments', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('actual_duration_minutes', sa.Integer(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table('appointments', schema=None) as batch_op:
        batch_op.drop_column('actual_duration_minutes')
