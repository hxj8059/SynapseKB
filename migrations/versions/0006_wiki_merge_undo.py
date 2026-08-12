"""Add reversible Wiki merge snapshots.

Revision ID: 0006_wiki_merge_undo
Revises: 0005_wiki_entity_resolution
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_wiki_merge_undo"
down_revision: str | None = "0005_wiki_entity_resolution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "wiki_entity_resolutions",
        sa.Column("merge_group_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "wiki_entity_resolutions",
        sa.Column("snapshot", sa.JSON(), server_default="{}", nullable=False),
    )
    op.add_column(
        "wiki_entity_resolutions",
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_wiki_entity_resolutions_merge_group_id"),
        "wiki_entity_resolutions",
        ["merge_group_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_wiki_entity_resolutions_reverted_at"),
        "wiki_entity_resolutions",
        ["reverted_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_wiki_entity_resolutions_reverted_at"),
        table_name="wiki_entity_resolutions",
    )
    op.drop_index(
        op.f("ix_wiki_entity_resolutions_merge_group_id"),
        table_name="wiki_entity_resolutions",
    )
    op.drop_column("wiki_entity_resolutions", "reverted_at")
    op.drop_column("wiki_entity_resolutions", "snapshot")
    op.drop_column("wiki_entity_resolutions", "merge_group_id")
