"""Add durable Wiki aliases and entity-resolution decisions.

Revision ID: 0005_wiki_entity_resolution
Revises: 0004_wiki_node_embeddings
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_wiki_entity_resolution"
down_revision: str | None = "0004_wiki_node_embeddings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wiki_node_aliases",
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.Uuid(), nullable=False),
        sa.Column("alias", sa.String(length=500), nullable=False),
        sa.Column("normalized_alias", sa.String(length=500), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["wiki_nodes.id"],
            name=op.f("fk_wiki_node_aliases_node_id_wiki_nodes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["space_id"],
            ["wiki_spaces.id"],
            name=op.f("fk_wiki_node_aliases_space_id_wiki_spaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wiki_node_aliases")),
        sa.UniqueConstraint(
            "space_id",
            "node_id",
            "normalized_alias",
            name="uq_wiki_node_alias_space_node_normalized",
        ),
    )
    op.create_index(
        op.f("ix_wiki_node_aliases_node_id"),
        "wiki_node_aliases",
        ["node_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_wiki_node_aliases_space_id"),
        "wiki_node_aliases",
        ["space_id"],
        unique=False,
    )
    op.create_index(
        "ix_wiki_node_alias_space_normalized",
        "wiki_node_aliases",
        ["space_id", "normalized_alias"],
        unique=False,
    )
    op.execute(
        """
        INSERT INTO wiki_node_aliases (
            id, space_id, node_id, alias, normalized_alias, source, created_at
        )
        SELECT
            gen_random_uuid(),
            space_id,
            id,
            label,
            lower(regexp_replace(label, '[[:space:][:punct:]]+', '', 'g')),
            'canonical',
            now()
        FROM wiki_nodes
        WHERE page_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )

    op.create_table(
        "wiki_entity_resolutions",
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("left_page_id", sa.Uuid(), nullable=False),
        sa.Column("right_page_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("canonical_page_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("decided_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["canonical_page_id"],
            ["wiki_pages.id"],
            name=op.f("fk_wiki_entity_resolutions_canonical_page_id_wiki_pages"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"],
            ["users.id"],
            name=op.f("fk_wiki_entity_resolutions_decided_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["left_page_id"],
            ["wiki_pages.id"],
            name=op.f("fk_wiki_entity_resolutions_left_page_id_wiki_pages"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["right_page_id"],
            ["wiki_pages.id"],
            name=op.f("fk_wiki_entity_resolutions_right_page_id_wiki_pages"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["space_id"],
            ["wiki_spaces.id"],
            name=op.f("fk_wiki_entity_resolutions_space_id_wiki_spaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wiki_entity_resolutions")),
        sa.UniqueConstraint(
            "space_id",
            "left_page_id",
            "right_page_id",
            name="uq_wiki_entity_resolution_pair",
        ),
    )
    for column in (
        "space_id",
        "left_page_id",
        "right_page_id",
        "decision",
        "canonical_page_id",
        "decided_by_user_id",
    ):
        op.create_index(
            op.f(f"ix_wiki_entity_resolutions_{column}"),
            "wiki_entity_resolutions",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in (
        "decided_by_user_id",
        "canonical_page_id",
        "decision",
        "right_page_id",
        "left_page_id",
        "space_id",
    ):
        op.drop_index(
            op.f(f"ix_wiki_entity_resolutions_{column}"),
            table_name="wiki_entity_resolutions",
        )
    op.drop_table("wiki_entity_resolutions")
    op.drop_index("ix_wiki_node_alias_space_normalized", table_name="wiki_node_aliases")
    op.drop_index(op.f("ix_wiki_node_aliases_space_id"), table_name="wiki_node_aliases")
    op.drop_index(op.f("ix_wiki_node_aliases_node_id"), table_name="wiki_node_aliases")
    op.drop_table("wiki_node_aliases")
