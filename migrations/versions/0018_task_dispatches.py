"""Transactional outbox for durable task delivery.
Revision ID: 0018_task_dispatches
Revises: 0017_account_approvals
"""

import sqlalchemy as sa
from alembic import op

revision = "0018_task_dispatches"
down_revision = "0017_account_approvals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_dispatches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("task_type", sa.String(40), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("queue_name", sa.String(40), nullable=False),
        sa.Column("actor_name", sa.String(80), nullable=False),
        sa.Column("redis_message_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error_summary", sa.String(1000)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("task_type", "task_id", name="uq_task_dispatch_identity"),
    )
    op.create_index("ix_task_dispatch_recovery", "task_dispatches", ["status", "available_at"])


def downgrade() -> None:
    op.drop_table("task_dispatches")
