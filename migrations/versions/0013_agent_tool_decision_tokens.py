"""Configure Agent tool-decision output independently.

Revision ID: 0013_agent_tool_tokens
Revises: 0012_wiki_index_page
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_agent_tool_tokens"
down_revision: str | None = "0012_wiki_index_page"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "tool_decision_max_tokens",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("4000"),
        ),
    )
    # Older runners allowed LangGraph to wrap a requested cancellation as an
    # exception, so user-cancelled runs were incorrectly stored as failed.
    op.execute(
        sa.text(
            """
            UPDATE agent_runs
            SET status = 'cancelled', error_summary = NULL
            WHERE status = 'failed'
              AND cancel_requested_at IS NOT NULL
              AND error_summary LIKE 'NodeCancelledError:%'
            """
        )
    )


def downgrade() -> None:
    op.drop_column("agents", "tool_decision_max_tokens")
