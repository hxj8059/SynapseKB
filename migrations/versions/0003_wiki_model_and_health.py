"""Add explicit Wiki model selection and Wiki health maintenance.

Revision ID: 0003_wiki_model_and_health
Revises: 0002_wiki_node_configuration
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_wiki_model_and_health"
down_revision: str | None = "0002_wiki_node_configuration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.add_column("knowledge_bases", sa.Column("wiki_chat_model_id", sa.Uuid(), nullable=True))
    op.add_column(
        "knowledge_bases",
        sa.Column(
            "wiki_health_check_enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
    )
    op.add_column(
        "knowledge_bases",
        sa.Column(
            "wiki_health_check_interval_hours",
            sa.Integer(),
            server_default="24",
            nullable=False,
        ),
    )
    op.create_foreign_key(
        op.f("fk_knowledge_bases_wiki_chat_model_id_models"),
        "knowledge_bases",
        "models",
        ["wiki_chat_model_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_knowledge_bases_wiki_chat_model_id"),
        "knowledge_bases",
        ["wiki_chat_model_id"],
        unique=False,
    )
    op.execute(
        """
        UPDATE knowledge_bases
        SET wiki_chat_model_id = (
            SELECT id FROM models
            WHERE kind = 'chat' AND is_enabled = true
            ORDER BY created_at, id
            LIMIT 1
        )
        WHERE wiki_chat_model_id IS NULL
        """
    )

    op.add_column("wiki_update_jobs", sa.Column("model_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_wiki_update_jobs_model_id_models"),
        "wiki_update_jobs",
        "models",
        ["model_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_wiki_update_jobs_model_id"),
        "wiki_update_jobs",
        ["model_id"],
        unique=False,
    )
    op.execute(
        """
        UPDATE wiki_update_jobs
        SET model_id = (
            SELECT id FROM models
            WHERE kind = 'chat'
            ORDER BY created_at, id
            LIMIT 1
        )
        WHERE model_id IS NULL
        """
    )

    op.add_column(
        "wiki_pages",
        sa.Column("is_archived", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("wiki_pages", sa.Column("merged_into_page_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_wiki_pages_merged_into_page_id_wiki_pages"),
        "wiki_pages",
        "wiki_pages",
        ["merged_into_page_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_wiki_pages_is_archived"), "wiki_pages", ["is_archived"], unique=False
    )
    op.create_index(
        op.f("ix_wiki_pages_merged_into_page_id"),
        "wiki_pages",
        ["merged_into_page_id"],
        unique=False,
    )
    op.create_index(
        "ix_wiki_nodes_label_trgm",
        "wiki_nodes",
        ["label"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"label": "gin_trgm_ops"},
    )

    op.create_table(
        "wiki_health_jobs",
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("auto_repair", sa.Boolean(), nullable=False),
        sa.Column("report", sa.JSON(), nullable=False),
        sa.Column("proposed_actions", sa.JSON(), nullable=False),
        sa.Column("applied_actions", sa.JSON(), nullable=False),
        sa.Column("error_summary", sa.String(length=1000), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["models.id"],
            name=op.f("fk_wiki_health_jobs_model_id_models"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["space_id"],
            ["wiki_spaces.id"],
            name=op.f("fk_wiki_health_jobs_space_id_wiki_spaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wiki_health_jobs")),
    )
    op.create_index(
        op.f("ix_wiki_health_jobs_model_id"), "wiki_health_jobs", ["model_id"], unique=False
    )
    op.create_index(
        op.f("ix_wiki_health_jobs_space_id"), "wiki_health_jobs", ["space_id"], unique=False
    )
    op.create_index(
        op.f("ix_wiki_health_jobs_status"), "wiki_health_jobs", ["status"], unique=False
    )
    op.create_index(
        op.f("ix_wiki_health_jobs_trigger"), "wiki_health_jobs", ["trigger"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_wiki_health_jobs_trigger"), table_name="wiki_health_jobs")
    op.drop_index(op.f("ix_wiki_health_jobs_status"), table_name="wiki_health_jobs")
    op.drop_index(op.f("ix_wiki_health_jobs_space_id"), table_name="wiki_health_jobs")
    op.drop_index(op.f("ix_wiki_health_jobs_model_id"), table_name="wiki_health_jobs")
    op.drop_table("wiki_health_jobs")
    op.drop_index("ix_wiki_nodes_label_trgm", table_name="wiki_nodes", postgresql_using="gin")
    op.drop_index(op.f("ix_wiki_pages_merged_into_page_id"), table_name="wiki_pages")
    op.drop_index(op.f("ix_wiki_pages_is_archived"), table_name="wiki_pages")
    op.drop_constraint(
        op.f("fk_wiki_pages_merged_into_page_id_wiki_pages"), "wiki_pages", type_="foreignkey"
    )
    op.drop_column("wiki_pages", "merged_into_page_id")
    op.drop_column("wiki_pages", "is_archived")
    op.drop_index(op.f("ix_wiki_update_jobs_model_id"), table_name="wiki_update_jobs")
    op.drop_constraint(
        op.f("fk_wiki_update_jobs_model_id_models"), "wiki_update_jobs", type_="foreignkey"
    )
    op.drop_column("wiki_update_jobs", "model_id")
    op.drop_index(
        op.f("ix_knowledge_bases_wiki_chat_model_id"), table_name="knowledge_bases"
    )
    op.drop_constraint(
        op.f("fk_knowledge_bases_wiki_chat_model_id_models"),
        "knowledge_bases",
        type_="foreignkey",
    )
    op.drop_column("knowledge_bases", "wiki_health_check_interval_hours")
    op.drop_column("knowledge_bases", "wiki_health_check_enabled")
    op.drop_column("knowledge_bases", "wiki_chat_model_id")
