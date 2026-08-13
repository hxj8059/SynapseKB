"""Store and index Embedding dimensions per knowledge base.

Revision ID: 0009_per_kb_embedding_dimensions
Revises: 0008_module_models
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0009_per_kb_embedding_dimensions"
down_revision: str | None = "0008_module_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_dimension_indexes(table: str, prefix: str) -> None:
    # These cover the dimensions used by most hosted Embedding models. A new
    # dimension remains fully functional with exact search and can receive its
    # own online expression index later without changing the application schema.
    for dimensions in (384, 512, 768, 1024, 1536, 2000):
        op.execute(
            f"""
            CREATE INDEX {prefix}_{dimensions}_hnsw
            ON {table} USING hnsw
            ((embedding::vector({dimensions})) vector_cosine_ops)
            WHERE vector_dims(embedding) = {dimensions}
            """
        )


def upgrade() -> None:
    op.add_column(
        "knowledge_bases",
        sa.Column(
            "embedding_dimensions",
            sa.Integer(),
            server_default="1536",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_knowledge_bases_embedding_dimensions",
        "knowledge_bases",
        "embedding_dimensions BETWEEN 1 AND 2000",
    )
    op.drop_index("ix_chunks_embedding_hnsw", table_name="chunks")
    op.drop_index("ix_wiki_nodes_embedding_hnsw", table_name="wiki_nodes")
    op.alter_column(
        "chunks",
        "embedding",
        type_=Vector(),
        postgresql_using="embedding::vector",
    )
    op.alter_column(
        "wiki_nodes",
        "embedding",
        type_=Vector(),
        postgresql_using="embedding::vector",
    )
    _create_dimension_indexes("chunks", "ix_chunks_embedding")
    _create_dimension_indexes("wiki_nodes", "ix_wiki_nodes_embedding")


def downgrade() -> None:
    for prefix in (
        "ix_wiki_nodes_embedding",
        "ix_chunks_embedding",
    ):
        for dimensions in (384, 512, 768, 1024, 1536, 2000):
            op.execute(f"DROP INDEX IF EXISTS {prefix}_{dimensions}_hnsw")
    op.execute(
        "ALTER TABLE wiki_nodes ALTER COLUMN embedding TYPE vector(1536) "
        "USING embedding::vector(1536)"
    )
    op.execute(
        "ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(1536) "
        "USING embedding::vector(1536)"
    )
    op.create_index(
        "ix_chunks_embedding_hnsw",
        "chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_wiki_nodes_embedding_hnsw",
        "wiki_nodes",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_constraint(
        "ck_knowledge_bases_embedding_dimensions",
        "knowledge_bases",
        type_="check",
    )
    op.drop_column("knowledge_bases", "embedding_dimensions")
