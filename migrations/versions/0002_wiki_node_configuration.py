"""Add configurable Wiki node types and generation metadata.

Revision ID: 0002_wiki_node_configuration
Revises: 0001_initial
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_wiki_node_configuration"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_bases",
        sa.Column(
            "wiki_node_types",
            postgresql.ARRAY(sa.String(length=40)),
            server_default=sa.text("ARRAY['主题']::varchar[]"),
            nullable=False,
        ),
    )
    op.add_column(
        "knowledge_bases",
        sa.Column(
            "wiki_generation_prompt",
            sa.Text(),
            server_default="",
            nullable=False,
        ),
    )
    op.add_column(
        "wiki_page_versions",
        sa.Column(
            "metadata",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("wiki_page_versions", "metadata")
    op.drop_column("knowledge_bases", "wiki_generation_prompt")
    op.drop_column("knowledge_bases", "wiki_node_types")
