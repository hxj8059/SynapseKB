"""Super administrator and auditable account approval requests.

Revision ID: 0017_account_approvals
Revises: 0016_chunk_ref_indexes
"""

import sqlalchemy as sa
from alembic import op

revision = "0017_account_approvals"
down_revision = "0016_chunk_ref_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("approval_status", sa.String(20), nullable=False, server_default="approved"),
    )
    op.create_index("ix_users_approval_status", "users", ["approval_status"])
    op.create_table(
        "user_approval_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("requested_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reviewed_by_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("review_note", sa.String(1000)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_user_approval_requests_status", "user_approval_requests", ["status"])
    op.execute("""UPDATE users SET role = 'super_admin' WHERE id = (
        SELECT id FROM users WHERE role = 'admin' AND is_active = true
        ORDER BY created_at, id LIMIT 1
    ) AND NOT EXISTS (SELECT 1 FROM users WHERE role = 'super_admin' AND is_active = true)""")


def downgrade() -> None:
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'super_admin'")
    op.drop_table("user_approval_requests")
    op.drop_index("ix_users_approval_status", table_name="users")
    op.drop_column("users", "approval_status")
