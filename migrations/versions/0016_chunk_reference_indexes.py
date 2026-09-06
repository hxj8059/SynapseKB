"""Index chunk references used by ON DELETE SET NULL foreign keys.

Revision ID: 0016_chunk_ref_indexes
Revises: 0015_kb_deletion
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016_chunk_ref_indexes"
down_revision: str | None = "0015_kb_deletion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # These tables can be large in production. PostgreSQL requires concurrent
    # index creation to run outside Alembic's surrounding transaction.
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_message_citations_chunk_id",
            "message_citations",
            ["chunk_id"],
            unique=False,
            postgresql_concurrently=True,
            if_not_exists=True,
        )
        op.create_index(
            "ix_wiki_page_sources_chunk_id",
            "wiki_page_sources",
            ["chunk_id"],
            unique=False,
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_wiki_page_sources_chunk_id",
            table_name="wiki_page_sources",
            postgresql_concurrently=True,
            if_exists=True,
        )
        op.drop_index(
            "ix_message_citations_chunk_id",
            table_name="message_citations",
            postgresql_concurrently=True,
            if_exists=True,
        )
