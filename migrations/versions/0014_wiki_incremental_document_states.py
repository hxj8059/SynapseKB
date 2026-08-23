"""Track Wiki work per document and distinguish incremental jobs from rebuilds.

Revision ID: 0014_wiki_doc_states
Revises: 0013_agent_tool_tokens
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_wiki_doc_states"
down_revision: str | None = "0013_agent_tool_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "wiki_update_jobs",
        sa.Column(
            "generation_mode",
            sa.String(length=32),
            nullable=False,
            server_default="incremental",
        ),
    )
    op.add_column(
        "wiki_update_jobs",
        sa.Column(
            "trigger",
            sa.String(length=32),
            nullable=False,
            server_default="automatic",
        ),
    )
    op.add_column(
        "wiki_update_jobs",
        sa.Column("retry_of_job_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_wiki_update_jobs_retry_of_job_id_wiki_update_jobs"),
        "wiki_update_jobs",
        "wiki_update_jobs",
        ["retry_of_job_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_wiki_update_jobs_generation_mode"),
        "wiki_update_jobs",
        ["generation_mode"],
        unique=False,
    )
    op.create_index(
        op.f("ix_wiki_update_jobs_trigger"),
        "wiki_update_jobs",
        ["trigger"],
        unique=False,
    )
    op.create_index(
        op.f("ix_wiki_update_jobs_retry_of_job_id"),
        "wiki_update_jobs",
        ["retry_of_job_id"],
        unique=False,
    )
    op.execute(
        sa.text(
            """
            UPDATE wiki_update_jobs
            SET generation_mode = 'rebuild', trigger = 'manual'
            WHERE cardinality(affected_document_ids) = 0
            """
        )
    )

    op.create_table(
        "wiki_document_states",
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("target_document_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_successful_document_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("last_job_id", sa.Uuid(), nullable=True),
        sa.Column("error_summary", sa.String(length=1000), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
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
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_wiki_document_states_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["last_job_id"],
            ["wiki_update_jobs.id"],
            name=op.f("fk_wiki_document_states_last_job_id_wiki_update_jobs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["space_id"],
            ["wiki_spaces.id"],
            name=op.f("fk_wiki_document_states_space_id_wiki_spaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wiki_document_states")),
        sa.UniqueConstraint(
            "space_id",
            "document_id",
            name="uq_wiki_document_state_space_document",
        ),
    )
    op.create_index(
        op.f("ix_wiki_document_states_space_id"),
        "wiki_document_states",
        ["space_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_wiki_document_states_document_id"),
        "wiki_document_states",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_wiki_document_states_status"),
        "wiki_document_states",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_wiki_document_states_space_status",
        "wiki_document_states",
        ["space_id", "status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_wiki_document_states_last_successful_document_updated_at"),
        "wiki_document_states",
        ["last_successful_document_updated_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_wiki_document_states_last_job_id"),
        "wiki_document_states",
        ["last_job_id"],
        unique=False,
    )
    # Existing published Wikis predate per-document state tracking. Build the
    # migration baseline only from documents proven to have reached a published
    # job or a currently published page. Merely being ready is insufficient:
    # otherwise a document from an old failed job would be incorrectly skipped.
    op.execute(
        sa.text(
            """
            WITH published_job_documents AS (
                SELECT
                    job.space_id,
                    parsed.document_id,
                    max(job.updated_at) AS processed_at
                FROM wiki_update_jobs AS job
                CROSS JOIN LATERAL (
                    SELECT raw_document_id::uuid AS document_id
                    FROM jsonb_array_elements_text(
                        CASE
                            WHEN jsonb_typeof(
                                job.quality_report::jsonb
                                #> '{document_coverage,expected_document_ids}'
                            ) = 'array'
                            THEN job.quality_report::jsonb
                                 #> '{document_coverage,expected_document_ids}'
                            ELSE '[]'::jsonb
                        END
                    ) AS raw(raw_document_id)
                    WHERE raw_document_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
                ) AS parsed
                WHERE job.status = 'published'
                GROUP BY job.space_id, parsed.document_id
            ),
            current_page_documents AS (
                SELECT
                    page.space_id,
                    source.document_id,
                    max(version.created_at) AS processed_at
                FROM wiki_pages AS page
                JOIN wiki_page_versions AS version
                  ON version.id = page.current_version_id
                JOIN wiki_page_sources AS source
                  ON source.page_version_id = version.id
                WHERE page.current_version_id IS NOT NULL
                  AND page.is_archived IS FALSE
                GROUP BY page.space_id, source.document_id
            ),
            published_documents AS (
                SELECT
                    space_id,
                    document_id,
                    max(processed_at) AS processed_at
                FROM (
                    SELECT * FROM published_job_documents
                    UNION ALL
                    SELECT * FROM current_page_documents
                ) AS evidence
                GROUP BY space_id, document_id
            )
            INSERT INTO wiki_document_states (
                id,
                space_id,
                document_id,
                status,
                target_document_updated_at,
                last_successful_document_updated_at,
                last_job_id,
                error_summary,
                attempt_count,
                processed_at,
                created_at,
                updated_at
            )
            SELECT
                gen_random_uuid(),
                published.space_id,
                document.id,
                CASE
                    WHEN document.updated_at <= published.processed_at
                    THEN 'succeeded'
                    ELSE 'pending'
                END,
                least(document.updated_at, published.processed_at),
                least(document.updated_at, published.processed_at),
                NULL,
                NULL,
                0,
                published.processed_at,
                now(),
                now()
            FROM published_documents AS published
            JOIN documents AS document ON document.id = published.document_id
            WHERE document.status = 'ready'
            ON CONFLICT (space_id, document_id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_table("wiki_document_states")
    op.drop_index(
        op.f("ix_wiki_update_jobs_retry_of_job_id"),
        table_name="wiki_update_jobs",
    )
    op.drop_index(op.f("ix_wiki_update_jobs_trigger"), table_name="wiki_update_jobs")
    op.drop_index(
        op.f("ix_wiki_update_jobs_generation_mode"),
        table_name="wiki_update_jobs",
    )
    op.drop_constraint(
        op.f("fk_wiki_update_jobs_retry_of_job_id_wiki_update_jobs"),
        "wiki_update_jobs",
        type_="foreignkey",
    )
    op.drop_column("wiki_update_jobs", "retry_of_job_id")
    op.drop_column("wiki_update_jobs", "trigger")
    op.drop_column("wiki_update_jobs", "generation_mode")
