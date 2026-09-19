"""add notifications table (N2-Persist, Phase 5B)

Revision ID: a91f3c7e2b44
Revises: eb348e90a283
Create Date: 2026-09-19

N2-Persist durable notification outbox/inbox (in-memory does not suffice:
retry state, cross-restart idempotency, and the in-app inbox itself must
be durable).

- Creates ``notifications`` (PK notification_id; nullable FKs to users,
  appointments, queue with SET NULL so history survives parent deletes;
  channel/type/status+attempts+safe error+template_ref+created_at/sent_at).
- Idempotency: ``uq_notifications_idempotency_key`` UNIQUE on
  ``idempotency_key`` (``type:appointment:channel`` or ``event:<id>``).
- Status/attempts guarded by named CHECKs (PENDING/SENT/FAILED,
  attempts >= 0). No server defaults (Python-side defaults only, per repo
  convention); no ``batch_op.f()`` (plain deterministic names).
- All indexes from the model metadata are created explicitly (both the
  ``index=True`` auto indexes and the hand-named composite ones) so
  ``alembic check`` reports no drift.
- Downgrade drops indexes then the table (data is an ephemeral outbox;
  best-effort downgrade drops it).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'a91f3c7e2b44'
down_revision: Union[str, None] = 'eb348e90a283'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'notifications',
        sa.Column('notification_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('appointment_id', sa.Integer(), nullable=True),
        sa.Column('queue_id', sa.Integer(), nullable=True),
        sa.Column('channel', sa.String(length=20), nullable=False),
        sa.Column('type', sa.String(length=40), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('template_ref', sa.String(length=100), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('idempotency_key', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('PENDING', 'SENT', 'FAILED')",
            name='ck_notifications_status_allowed',
        ),
        sa.CheckConstraint('attempts >= 0', name='ck_notifications_attempts_non_negative'),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.user_id'],
            name='fk_notifications_user_id_users', ondelete='SET NULL'),
        sa.ForeignKeyConstraint(
            ['appointment_id'], ['appointments.appointment_id'],
            name='fk_notifications_appointment_id_appointments', ondelete='SET NULL'),
        sa.ForeignKeyConstraint(
            ['queue_id'], ['queue.queue_id'],
            name='fk_notifications_queue_id_queue', ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('notification_id'),
        sa.UniqueConstraint('idempotency_key', name='uq_notifications_idempotency_key'),
    )
    # index=True auto indexes (mirrors model metadata names exactly).
    op.create_index('ix_notifications_user_id', 'notifications', ['user_id'], unique=False)
    op.create_index(
        'ix_notifications_appointment_id', 'notifications', ['appointment_id'], unique=False
    )
    op.create_index('ix_notifications_queue_id', 'notifications', ['queue_id'], unique=False)
    op.create_index('ix_notifications_channel', 'notifications', ['channel'], unique=False)
    op.create_index('ix_notifications_type', 'notifications', ['type'], unique=False)
    op.create_index('ix_notifications_status', 'notifications', ['status'], unique=False)
    # Hand-named composite indexes from __table_args__.
    op.create_index(
        'ix_notifications_status_created', 'notifications', ['status', 'created_at'],
        unique=False,
    )
    op.create_index(
        'ix_notifications_type_channel', 'notifications', ['type', 'channel'], unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_notifications_type_channel', table_name='notifications')
    op.drop_index('ix_notifications_status_created', table_name='notifications')
    op.drop_index('ix_notifications_status', table_name='notifications')
    op.drop_index('ix_notifications_type', table_name='notifications')
    op.drop_index('ix_notifications_channel', table_name='notifications')
    op.drop_index('ix_notifications_queue_id', table_name='notifications')
    op.drop_index('ix_notifications_appointment_id', table_name='notifications')
    op.drop_index('ix_notifications_user_id', table_name='notifications')
    op.drop_table('notifications')
