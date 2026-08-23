"""Add durable asynchronous knowledge-base deletion jobs.

Revision ID: 0015_kb_deletion
Revises: 0014_wiki_doc_states
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_kb_deletion"
down_revision: str | None = "0014_wiki_doc_states"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_bases",
        sa.Column(
            "lifecycle_status",
            sa.String(length=32),
            nullable=False,
            server_default="active",
        ),
    )
    op.create_index(
        op.f("ix_knowledge_bases_lifecycle_status"),
        "knowledge_bases",
        ["lifecycle_status"],
        unique=False,
    )
    op.create_table(
        "knowledge_base_deletion_jobs",
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=True),
        sa.Column("knowledge_base_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_name", sa.String(length=160), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=80), nullable=True),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("document_count", sa.Integer(), nullable=False),
        sa.Column("total_object_count", sa.Integer(), nullable=False),
        sa.Column("deleted_object_count", sa.Integer(), nullable=False),
        sa.Column("error_summary", sa.String(length=1000), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["knowledge_bases.id"],
            name=op.f(
                "fk_knowledge_base_deletion_jobs_knowledge_base_id_knowledge_bases"
            ),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_id"],
            ["users.id"],
            name=op.f("fk_knowledge_base_deletion_jobs_requested_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_base_deletion_jobs")),
    )
    for column in (
        "knowledge_base_id",
        "knowledge_base_snapshot_id",
        "requested_by_id",
        "status",
    ):
        op.create_index(
            op.f(f"ix_knowledge_base_deletion_jobs_{column}"),
            "knowledge_base_deletion_jobs",
            [column],
            unique=False,
        )
    op.create_index(
        "uq_kb_deletion_active_job",
        "knowledge_base_deletion_jobs",
        ["knowledge_base_snapshot_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running', 'waiting_tasks')"),
    )


def downgrade() -> None:
    op.drop_table("knowledge_base_deletion_jobs")
    op.drop_index(
        op.f("ix_knowledge_bases_lifecycle_status"),
        table_name="knowledge_bases",
    )
    op.drop_column("knowledge_bases", "lifecycle_status")
