"""Add per-knowledge-base source-time extraction model.

Revision ID: 0011_source_time_chat
Revises: 0010_agent_run_history
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_source_time_chat"
down_revision: str | None = "0010_agent_run_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_bases",
        sa.Column("source_time_chat_model_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_knowledge_bases_source_time_chat_model_id_models",
        "knowledge_bases",
        "models",
        ["source_time_chat_model_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_knowledge_bases_source_time_chat_model_id",
        "knowledge_bases",
        ["source_time_chat_model_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_bases_source_time_chat_model_id",
        table_name="knowledge_bases",
    )
    op.drop_constraint(
        "fk_knowledge_bases_source_time_chat_model_id_models",
        "knowledge_bases",
        type_="foreignkey",
    )
    op.drop_column("knowledge_bases", "source_time_chat_model_id")
