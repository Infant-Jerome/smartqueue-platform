"""add password_reset_tokens table (Forgot Password + Email OTP)

Revision ID: d4e5f6a7b8c9
Revises: c9d1e2f3a4b5
Create Date: 2026-09-24

New table only; no existing table touched, no data migration:
- password_reset_tokens (reset_id PK, user_id FK -> users.user_id
  ON DELETE CASCADE, otp_hash, expires_at, attempts, verified_at,
  used_at, created_at) + two lookup indexes.
- Downgrade drops the table. SQLite-safe (create_table, no batch).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c9d1e2f3a4b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'password_reset_tokens',
        sa.Column('reset_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('otp_hash', sa.String(length=128), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('verified_at', sa.DateTime(), nullable=True),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('reset_id'),
    )
    op.create_index('ix_password_reset_user_id', 'password_reset_tokens', ['user_id'], unique=False)
    op.create_index('ix_password_reset_user_active', 'password_reset_tokens', ['user_id', 'used_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_password_reset_user_active', table_name='password_reset_tokens')
    op.drop_index('ix_password_reset_user_id', table_name='password_reset_tokens')
    op.drop_table('password_reset_tokens')
