"""Add indexes for the paginated Wiki directory.

Revision ID: 0012_wiki_index_page
Revises: 0011_source_time_chat
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_wiki_index_page"
down_revision: str | None = "0011_source_time_chat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PUBLISHED_PAGE_PREDICATE = "current_version_id IS NOT NULL AND is_archived = false"


def upgrade() -> None:
    op.create_index(
        "ix_wiki_nodes_space_page",
        "wiki_nodes",
        ["space_id", "page_id"],
        unique=False,
        postgresql_include=["node_type"],
        postgresql_where=sa.text("page_id IS NOT NULL"),
    )
    op.create_index(
        "ix_wiki_pages_published_order",
        "wiki_pages",
        ["space_id", "sort_order", "title", "id"],
        unique=False,
        postgresql_where=sa.text(PUBLISHED_PAGE_PREDICATE),
    )
    op.create_index(
        "ix_wiki_pages_title_trgm",
        "wiki_pages",
        ["title"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )
    for field in ("source_time", "created_at", "updated_at"):
        op.create_index(
            f"ix_wiki_pages_published_{field}",
            "wiki_pages",
            ["space_id", field],
            unique=False,
            postgresql_where=sa.text(PUBLISHED_PAGE_PREDICATE),
        )


def downgrade() -> None:
    for field in reversed(("source_time", "created_at", "updated_at")):
        op.drop_index(f"ix_wiki_pages_published_{field}", table_name="wiki_pages")
    op.drop_index("ix_wiki_pages_title_trgm", table_name="wiki_pages")
    op.drop_index("ix_wiki_pages_published_order", table_name="wiki_pages")
    op.drop_index("ix_wiki_nodes_space_page", table_name="wiki_nodes")
