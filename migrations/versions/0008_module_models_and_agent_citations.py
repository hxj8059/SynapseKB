"""Configure models per module and persist Agent citations.

Revision ID: 0008_module_models
Revises: 0007_wiki_automatic_resolution
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_module_models"
down_revision: str | None = "0007_wiki_automatic_resolution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_model_reference(column_name: str) -> None:
    op.add_column("knowledge_bases", sa.Column(column_name, sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f(f"fk_knowledge_bases_{column_name}_models"),
        "knowledge_bases",
        "models",
        [column_name],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f(f"ix_knowledge_bases_{column_name}"),
        "knowledge_bases",
        [column_name],
        unique=False,
    )


def upgrade() -> None:
    _add_model_reference("rag_chat_model_id")
    _add_model_reference("rerank_model_id")
    _add_model_reference("wiki_health_chat_model_id")
    op.add_column(
        "knowledge_bases",
        sa.Column("rag_max_output_tokens", sa.Integer(), server_default="8000", nullable=False),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "citations",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE knowledge_bases
        SET rag_chat_model_id = wiki_chat_model_id,
            wiki_health_chat_model_id = wiki_chat_model_id
        WHERE wiki_chat_model_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE knowledge_bases
        SET rerank_model_id = (
            SELECT id FROM models
            WHERE kind = 'rerank' AND is_enabled = true
            ORDER BY created_at, id LIMIT 1
        )
        WHERE rerank_model_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "citations")
    op.drop_column("knowledge_bases", "rag_max_output_tokens")
    for column_name in (
        "wiki_health_chat_model_id",
        "rerank_model_id",
        "rag_chat_model_id",
    ):
        op.drop_index(op.f(f"ix_knowledge_bases_{column_name}"), table_name="knowledge_bases")
        op.drop_constraint(
            op.f(f"fk_knowledge_bases_{column_name}_models"),
            "knowledge_bases",
            type_="foreignkey",
        )
        op.drop_column("knowledge_bases", column_name)
