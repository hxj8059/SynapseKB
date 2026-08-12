"""Allow audited automatic Wiki entity resolution.

Revision ID: 0007_wiki_automatic_resolution
Revises: 0006_wiki_merge_undo
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_wiki_automatic_resolution"
down_revision: str | None = "0006_wiki_merge_undo"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "wiki_entity_resolutions",
        sa.Column(
            "decision_source",
            sa.String(length=20),
            server_default="manual",
            nullable=False,
        ),
    )
    op.create_index(
        op.f("ix_wiki_entity_resolutions_decision_source"),
        "wiki_entity_resolutions",
        ["decision_source"],
        unique=False,
    )
    op.alter_column(
        "wiki_entity_resolutions",
        "decided_by_user_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )


def downgrade() -> None:
    # Automatic records cannot satisfy the old NOT NULL constraint. Removing
    # those records is safer than attributing them to an arbitrary administrator.
    op.execute(
        "DELETE FROM wiki_entity_resolutions "
        "WHERE decision_source = 'llm_auto' AND decided_by_user_id IS NULL"
    )
    op.alter_column(
        "wiki_entity_resolutions",
        "decided_by_user_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
    op.drop_index(
        op.f("ix_wiki_entity_resolutions_decision_source"),
        table_name="wiki_entity_resolutions",
    )
    op.drop_column("wiki_entity_resolutions", "decision_source")
