"""Add semantic embeddings for Wiki node entity resolution.

Revision ID: 0004_wiki_node_embeddings
Revises: 0003_wiki_model_and_health
"""

from collections.abc import Sequence

import pgvector.sqlalchemy.vector
import sqlalchemy as sa
from alembic import op

revision: str = "0004_wiki_node_embeddings"
down_revision: str | None = "0003_wiki_model_and_health"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "wiki_nodes",
        sa.Column(
            "embedding",
            pgvector.sqlalchemy.vector.VECTOR(dim=1536),
            nullable=True,
        ),
    )
    op.add_column("wiki_nodes", sa.Column("embedding_model_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_wiki_nodes_embedding_model_id_models"),
        "wiki_nodes",
        "models",
        ["embedding_model_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_wiki_nodes_embedding_model_id"),
        "wiki_nodes",
        ["embedding_model_id"],
        unique=False,
    )
    op.create_index(
        "ix_wiki_nodes_embedding_hnsw",
        "wiki_nodes",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index(
        "ix_wiki_nodes_embedding_hnsw", table_name="wiki_nodes", postgresql_using="hnsw"
    )
    op.drop_index(op.f("ix_wiki_nodes_embedding_model_id"), table_name="wiki_nodes")
    op.drop_constraint(
        op.f("fk_wiki_nodes_embedding_model_id_models"), "wiki_nodes", type_="foreignkey"
    )
    op.drop_column("wiki_nodes", "embedding_model_id")
    op.drop_column("wiki_nodes", "embedding")
