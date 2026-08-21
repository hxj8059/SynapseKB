"""Index per-user Agent run history.

Revision ID: 0010_agent_run_history
Revises: 0009_per_kb_embedding_dimensions
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010_agent_run_history"
down_revision: str | None = "0009_per_kb_embedding_dimensions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_agent_runs_user_agent_created",
        "agent_runs",
        ["user_id", "agent_id", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_agent_runs_user_agent_created", table_name="agent_runs")
