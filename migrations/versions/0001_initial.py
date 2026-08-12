"""Initial SynapseKB schema.

Revision ID: 0001_initial
Revises: None
"""

from collections.abc import Sequence

import pgvector.sqlalchemy.vector
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "models",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("encrypted_api_key", sa.LargeBinary(), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("max_concurrency", sa.Integer(), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_models")),
        sa.UniqueConstraint("name", name=op.f("uq_models_name")),
    )
    op.create_index(op.f("ix_models_is_enabled"), "models", ["is_enabled"], unique=False)
    op.create_index(op.f("ix_models_kind"), "models", ["kind"], unique=False)
    op.create_index(op.f("ix_models_provider"), "models", ["provider"], unique=False)
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_is_active"), "users", ["is_active"], unique=False)
    op.create_index(op.f("ix_users_role"), "users", ["role"], unique=False)
    op.create_table(
        "agents",
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("avatar", sa.String(length=1000), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("chat_model_id", sa.Uuid(), nullable=False),
        sa.Column("visibility", sa.String(length=20), nullable=False),
        sa.Column("max_steps", sa.Integer(), nullable=False),
        sa.Column("max_tokens", sa.Integer(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("recommended_questions", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
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
            ["chat_model_id"],
            ["models.id"],
            name=op.f("fk_agents_chat_model_id_models"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_agents_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agents")),
        sa.UniqueConstraint("name", name=op.f("uq_agents_name")),
    )
    op.create_index(op.f("ix_agents_visibility"), "agents", ["visibility"], unique=False)
    op.create_table(
        "audit_logs",
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_audit_logs_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"], unique=False)
    op.create_index(
        op.f("ix_audit_logs_actor_user_id"), "audit_logs", ["actor_user_id"], unique=False
    )
    op.create_index(op.f("ix_audit_logs_created_at"), "audit_logs", ["created_at"], unique=False)
    op.create_index(op.f("ix_audit_logs_request_id"), "audit_logs", ["request_id"], unique=False)
    op.create_index(op.f("ix_audit_logs_resource_id"), "audit_logs", ["resource_id"], unique=False)
    op.create_index(
        op.f("ix_audit_logs_resource_type"), "audit_logs", ["resource_type"], unique=False
    )
    op.create_table(
        "chat_sessions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
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
            ["user_id"],
            ["users.id"],
            name=op.f("fk_chat_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_sessions")),
    )
    op.create_index(op.f("ix_chat_sessions_user_id"), "chat_sessions", ["user_id"], unique=False)
    op.create_table(
        "knowledge_bases",
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("visibility", sa.String(length=20), nullable=False),
        sa.Column("embedding_model_id", sa.Uuid(), nullable=True),
        sa.Column("wiki_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
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
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_knowledge_bases_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["embedding_model_id"],
            ["models.id"],
            name=op.f("fk_knowledge_bases_embedding_model_id_models"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_bases")),
        sa.UniqueConstraint("name", name=op.f("uq_knowledge_bases_name")),
    )
    op.create_index(
        op.f("ix_knowledge_bases_visibility"), "knowledge_bases", ["visibility"], unique=False
    )
    op.create_table(
        "personal_access_tokens",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("token_prefix", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.String(length=40)), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_personal_access_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_personal_access_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_personal_access_tokens_token_hash")),
    )
    op.create_index(
        op.f("ix_personal_access_tokens_expires_at"),
        "personal_access_tokens",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_personal_access_tokens_token_prefix"),
        "personal_access_tokens",
        ["token_prefix"],
        unique=False,
    )
    op.create_index(
        op.f("ix_personal_access_tokens_user_id"),
        "personal_access_tokens",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_id", sa.Uuid(), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["replaced_by_id"],
            ["refresh_tokens.id"],
            name=op.f("fk_refresh_tokens_replaced_by_id_refresh_tokens"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index(
        op.f("ix_refresh_tokens_expires_at"), "refresh_tokens", ["expires_at"], unique=False
    )
    op.create_index(
        op.f("ix_refresh_tokens_family_id"), "refresh_tokens", ["family_id"], unique=False
    )
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False)
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(length=160), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
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
            ["updated_by_id"],
            ["users.id"],
            name=op.f("fk_system_settings_updated_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_system_settings")),
    )
    op.create_table(
        "agent_knowledge_bases",
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_agent_knowledge_bases_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["knowledge_bases.id"],
            name=op.f("fk_agent_knowledge_bases_knowledge_base_id_knowledge_bases"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "agent_id", "knowledge_base_id", name=op.f("pk_agent_knowledge_bases")
        ),
    )
    op.create_table(
        "agent_runs",
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("resolved_time_summary", sa.Text(), nullable=True),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("error_summary", sa.String(length=1000), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
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
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_agent_runs_agent_id_agents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.id"],
            name=op.f("fk_agent_runs_session_id_chat_sessions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_agent_runs_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_runs")),
    )
    op.create_index(op.f("ix_agent_runs_agent_id"), "agent_runs", ["agent_id"], unique=False)
    op.create_index(op.f("ix_agent_runs_status"), "agent_runs", ["status"], unique=False)
    op.create_index(op.f("ix_agent_runs_user_id"), "agent_runs", ["user_id"], unique=False)
    op.create_table(
        "agent_users",
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_agent_users_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_agent_users_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("agent_id", "user_id", name=op.f("pk_agent_users")),
    )
    op.create_table(
        "chat_messages",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Uuid(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("retrieval_params", sa.JSON(), nullable=False),
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
            ["model_id"],
            ["models.id"],
            name=op.f("fk_chat_messages_model_id_models"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.id"],
            name=op.f("fk_chat_messages_session_id_chat_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_messages")),
    )
    op.create_index(
        op.f("ix_chat_messages_session_id"), "chat_messages", ["session_id"], unique=False
    )
    op.create_table(
        "document_tags",
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("color", sa.String(length=20), nullable=True),
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
            name=op.f("fk_document_tags_knowledge_base_id_knowledge_bases"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_tags")),
        sa.UniqueConstraint("knowledge_base_id", "name", name="uq_document_tag_kb_name"),
    )
    op.create_index(
        op.f("ix_document_tags_knowledge_base_id"),
        "document_tags",
        ["knowledge_base_id"],
        unique=False,
    )
    op.create_table(
        "documents",
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("media_type", sa.String(length=200), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("object_key", sa.String(length=1000), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("parsed_text_key", sa.String(length=1000), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("parse_config", sa.JSON(), nullable=False),
        sa.Column("error_summary", sa.String(length=1000), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
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
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_documents_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["knowledge_bases.id"],
            name=op.f("fk_documents_knowledge_base_id_knowledge_bases"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint("knowledge_base_id", "sha256", name="uq_document_kb_sha256"),
        sa.UniqueConstraint("object_key", name=op.f("uq_documents_object_key")),
    )
    op.create_index(
        "ix_documents_kb_created_at", "documents", ["knowledge_base_id", "created_at"], unique=False
    )
    op.create_index(
        "ix_documents_kb_source_time",
        "documents",
        ["knowledge_base_id", "source_time"],
        unique=False,
    )
    op.create_index(
        "ix_documents_kb_updated_at", "documents", ["knowledge_base_id", "updated_at"], unique=False
    )
    op.create_index(
        op.f("ix_documents_knowledge_base_id"), "documents", ["knowledge_base_id"], unique=False
    )
    op.create_index(op.f("ix_documents_sha256"), "documents", ["sha256"], unique=False)
    op.create_index(op.f("ix_documents_source_time"), "documents", ["source_time"], unique=False)
    op.create_index(op.f("ix_documents_status"), "documents", ["status"], unique=False)
    op.create_index(op.f("ix_documents_title"), "documents", ["title"], unique=False)
    op.create_table(
        "knowledge_base_members",
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["knowledge_bases.id"],
            name=op.f("fk_knowledge_base_members_knowledge_base_id_knowledge_bases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_knowledge_base_members_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "knowledge_base_id", "user_id", name=op.f("pk_knowledge_base_members")
        ),
        sa.UniqueConstraint("knowledge_base_id", "user_id", name="uq_kb_member"),
    )
    op.create_table(
        "wiki_spaces",
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("published_version", sa.Integer(), nullable=True),
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
            name=op.f("fk_wiki_spaces_knowledge_base_id_knowledge_bases"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wiki_spaces")),
        sa.UniqueConstraint("knowledge_base_id", name=op.f("uq_wiki_spaces_knowledge_base_id")),
    )
    op.create_table(
        "agent_steps",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("tool_name", sa.String(length=80), nullable=True),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("output_summary", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
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
            ["run_id"],
            ["agent_runs.id"],
            name=op.f("fk_agent_steps_run_id_agent_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_steps")),
        sa.UniqueConstraint("run_id", "ordinal", name="uq_agent_step_run_ordinal"),
    )
    op.create_index(op.f("ix_agent_steps_run_id"), "agent_steps", ["run_id"], unique=False)
    op.create_table(
        "chunks",
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=1536), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("page_from", sa.Integer(), nullable=True),
        sa.Column("page_to", sa.Integer(), nullable=True),
        sa.Column("section", sa.String(length=500), nullable=True),
        sa.Column("source_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
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
            name=op.f("fk_chunks_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["knowledge_bases.id"],
            name=op.f("fk_chunks_knowledge_base_id_knowledge_bases"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chunks")),
    )
    op.create_index(op.f("ix_chunks_document_id"), "chunks", ["document_id"], unique=False)
    op.create_index(
        "ix_chunks_embedding_hnsw",
        "chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_chunks_kb_created_at", "chunks", ["knowledge_base_id", "created_at"], unique=False
    )
    op.create_index(
        "ix_chunks_kb_source_time", "chunks", ["knowledge_base_id", "source_time"], unique=False
    )
    op.create_index(
        "ix_chunks_kb_updated_at", "chunks", ["knowledge_base_id", "updated_at"], unique=False
    )
    op.create_index(
        op.f("ix_chunks_knowledge_base_id"), "chunks", ["knowledge_base_id"], unique=False
    )
    op.create_index(
        "ix_chunks_search_vector", "chunks", ["search_vector"], unique=False, postgresql_using="gin"
    )
    op.create_index(op.f("ix_chunks_source_time"), "chunks", ["source_time"], unique=False)
    op.create_index(op.f("ix_chunks_status"), "chunks", ["status"], unique=False)
    op.create_table(
        "document_tag_links",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_tag_links_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["document_tags.id"],
            name=op.f("fk_document_tag_links_tag_id_document_tags"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("document_id", "tag_id", name=op.f("pk_document_tag_links")),
    )
    op.create_table(
        "processing_jobs",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("stage", sa.String(length=80), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("external_task_id", sa.String(length=200), nullable=True),
        sa.Column("error_summary", sa.String(length=1000), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
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
            name=op.f("fk_processing_jobs_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_processing_jobs")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_processing_jobs_idempotency_key")),
    )
    op.create_index(
        op.f("ix_processing_jobs_document_id"), "processing_jobs", ["document_id"], unique=False
    )
    op.create_index(
        op.f("ix_processing_jobs_external_task_id"),
        "processing_jobs",
        ["external_task_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_processing_jobs_job_type"), "processing_jobs", ["job_type"], unique=False
    )
    op.create_index(op.f("ix_processing_jobs_status"), "processing_jobs", ["status"], unique=False)
    op.create_table(
        "wiki_pages",
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("slug", sa.String(length=300), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("source_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
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
            ["parent_id"],
            ["wiki_pages.id"],
            name=op.f("fk_wiki_pages_parent_id_wiki_pages"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["space_id"],
            ["wiki_spaces.id"],
            name=op.f("fk_wiki_pages_space_id_wiki_spaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wiki_pages")),
        sa.UniqueConstraint("space_id", "slug", name="uq_wiki_page_space_slug"),
    )
    op.create_index(op.f("ix_wiki_pages_source_time"), "wiki_pages", ["source_time"], unique=False)
    op.create_index(op.f("ix_wiki_pages_space_id"), "wiki_pages", ["space_id"], unique=False)
    op.create_table(
        "wiki_update_jobs",
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("generation_id", sa.Uuid(), nullable=False),
        sa.Column("affected_document_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("candidate_version", sa.Integer(), nullable=True),
        sa.Column("quality_report", sa.JSON(), nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("error_summary", sa.String(length=1000), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
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
            ["space_id"],
            ["wiki_spaces.id"],
            name=op.f("fk_wiki_update_jobs_space_id_wiki_spaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wiki_update_jobs")),
        sa.UniqueConstraint("generation_id", name=op.f("uq_wiki_update_jobs_generation_id")),
    )
    op.create_index(
        op.f("ix_wiki_update_jobs_space_id"), "wiki_update_jobs", ["space_id"], unique=False
    )
    op.create_index(
        op.f("ix_wiki_update_jobs_status"), "wiki_update_jobs", ["status"], unique=False
    )
    op.create_table(
        "message_citations",
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=True),
        sa.Column("citation_number", sa.Integer(), nullable=False),
        sa.Column("document_title", sa.String(length=500), nullable=False),
        sa.Column("page_from", sa.Integer(), nullable=True),
        sa.Column("page_to", sa.Integer(), nullable=True),
        sa.Column("section", sa.String(length=500), nullable=True),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("source_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["chunks.id"],
            name=op.f("fk_message_citations_chunk_id_chunks"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["chat_messages.id"],
            name=op.f("fk_message_citations_message_id_chat_messages"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_message_citations")),
    )
    op.create_index(
        op.f("ix_message_citations_message_id"), "message_citations", ["message_id"], unique=False
    )
    op.create_table(
        "wiki_nodes",
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("node_type", sa.String(length=30), nullable=False),
        sa.Column("label", sa.String(length=500), nullable=False),
        sa.Column("page_id", sa.Uuid(), nullable=True),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("source_document_id", sa.Uuid(), nullable=True),
        sa.Column("source_page_id", sa.Uuid(), nullable=True),
        sa.Column("source_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
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
            name=op.f("fk_wiki_nodes_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["page_id"],
            ["wiki_pages.id"],
            name=op.f("fk_wiki_nodes_page_id_wiki_pages"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["documents.id"],
            name=op.f("fk_wiki_nodes_source_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_page_id"],
            ["wiki_pages.id"],
            name=op.f("fk_wiki_nodes_source_page_id_wiki_pages"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["space_id"],
            ["wiki_spaces.id"],
            name=op.f("fk_wiki_nodes_space_id_wiki_spaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wiki_nodes")),
    )
    op.create_index(op.f("ix_wiki_nodes_label"), "wiki_nodes", ["label"], unique=False)
    op.create_index(op.f("ix_wiki_nodes_node_type"), "wiki_nodes", ["node_type"], unique=False)
    op.create_index(op.f("ix_wiki_nodes_source_time"), "wiki_nodes", ["source_time"], unique=False)
    op.create_index(op.f("ix_wiki_nodes_space_id"), "wiki_nodes", ["space_id"], unique=False)
    op.create_index(
        "ix_wiki_nodes_space_source_time", "wiki_nodes", ["space_id", "source_time"], unique=False
    )
    op.create_table(
        "wiki_page_versions",
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("protected_blocks", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("generation_id", sa.Uuid(), nullable=True),
        sa.Column("change_summary", sa.Text(), nullable=False),
        sa.Column("is_manual", sa.Boolean(), nullable=False),
        sa.Column("source_time", sa.DateTime(timezone=True), nullable=True),
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
            ["page_id"],
            ["wiki_pages.id"],
            name=op.f("fk_wiki_page_versions_page_id_wiki_pages"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wiki_page_versions")),
        sa.UniqueConstraint("page_id", "version_number", name="uq_wiki_page_version"),
    )
    op.create_index(
        op.f("ix_wiki_page_versions_generation_id"),
        "wiki_page_versions",
        ["generation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_wiki_page_versions_page_id"), "wiki_page_versions", ["page_id"], unique=False
    )
    op.create_index(
        op.f("ix_wiki_page_versions_source_time"),
        "wiki_page_versions",
        ["source_time"],
        unique=False,
    )
    op.create_table(
        "wiki_edges",
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("source_node_id", sa.Uuid(), nullable=False),
        sa.Column("target_node_id", sa.Uuid(), nullable=False),
        sa.Column("edge_type", sa.String(length=40), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("source_document_id", sa.Uuid(), nullable=True),
        sa.Column("source_page_id", sa.Uuid(), nullable=True),
        sa.Column("source_time", sa.DateTime(timezone=True), nullable=True),
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
            ["source_document_id"],
            ["documents.id"],
            name=op.f("fk_wiki_edges_source_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_node_id"],
            ["wiki_nodes.id"],
            name=op.f("fk_wiki_edges_source_node_id_wiki_nodes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_page_id"],
            ["wiki_pages.id"],
            name=op.f("fk_wiki_edges_source_page_id_wiki_pages"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["space_id"],
            ["wiki_spaces.id"],
            name=op.f("fk_wiki_edges_space_id_wiki_spaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_node_id"],
            ["wiki_nodes.id"],
            name=op.f("fk_wiki_edges_target_node_id_wiki_nodes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wiki_edges")),
    )
    op.create_index(op.f("ix_wiki_edges_edge_type"), "wiki_edges", ["edge_type"], unique=False)
    op.create_index(
        op.f("ix_wiki_edges_source_node_id"), "wiki_edges", ["source_node_id"], unique=False
    )
    op.create_index(op.f("ix_wiki_edges_source_time"), "wiki_edges", ["source_time"], unique=False)
    op.create_index(op.f("ix_wiki_edges_space_id"), "wiki_edges", ["space_id"], unique=False)
    op.create_index(
        "ix_wiki_edges_space_source_time", "wiki_edges", ["space_id", "source_time"], unique=False
    )
    op.create_index(
        op.f("ix_wiki_edges_target_node_id"), "wiki_edges", ["target_node_id"], unique=False
    )
    op.create_table(
        "wiki_page_sources",
        sa.Column("page_version_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=True),
        sa.Column("paragraph_key", sa.String(length=120), nullable=False),
        sa.Column("evidence_text", sa.Text(), nullable=False),
        sa.Column("source_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["chunks.id"],
            name=op.f("fk_wiki_page_sources_chunk_id_chunks"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_wiki_page_sources_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["page_version_id"],
            ["wiki_page_versions.id"],
            name=op.f("fk_wiki_page_sources_page_version_id_wiki_page_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wiki_page_sources")),
    )
    op.create_index(
        op.f("ix_wiki_page_sources_document_id"), "wiki_page_sources", ["document_id"], unique=False
    )
    op.create_index(
        op.f("ix_wiki_page_sources_page_version_id"),
        "wiki_page_sources",
        ["page_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_wiki_page_sources_source_time"), "wiki_page_sources", ["source_time"], unique=False
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    op.drop_table("wiki_page_sources")
    op.drop_table("wiki_edges")
    op.drop_table("wiki_page_versions")
    op.drop_table("wiki_nodes")
    op.drop_table("message_citations")
    op.drop_table("wiki_update_jobs")
    op.drop_table("wiki_pages")
    op.drop_table("processing_jobs")
    op.drop_table("document_tag_links")
    op.drop_table("chunks")
    op.drop_table("agent_steps")
    op.drop_table("wiki_spaces")
    op.drop_table("knowledge_base_members")
    op.drop_table("documents")
    op.drop_table("document_tags")
    op.drop_table("chat_messages")
    op.drop_table("agent_users")
    op.drop_table("agent_runs")
    op.drop_table("agent_knowledge_bases")
    op.drop_table("system_settings")
    op.drop_table("refresh_tokens")
    op.drop_table("personal_access_tokens")
    op.drop_table("knowledge_bases")
    op.drop_table("chat_sessions")
    op.drop_table("audit_logs")
    op.drop_table("agents")
    op.drop_table("users")
    op.drop_table("models")
