from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from synapsekb.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="user", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")


class RefreshToken(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("refresh_tokens.id", ondelete="SET NULL")
    )
    user_agent: Mapped[str | None] = mapped_column(String(500))
    ip_address: Mapped[str | None] = mapped_column(String(64))


class PersonalAccessToken(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "personal_access_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    token_prefix: Mapped[str] = mapped_column(String(16), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String(40)), default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProviderModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "models"

    name: Mapped[str] = mapped_column(String(120), unique=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    base_url: Mapped[str] = mapped_column(String(500))
    model_name: Mapped[str] = mapped_column(String(200))
    encrypted_api_key: Mapped[bytes | None] = mapped_column(LargeBinary)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=60)
    max_concurrency: Mapped[int] = mapped_column(Integer, default=5)
    embedding_dimensions: Mapped[int | None] = mapped_column(Integer)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class KnowledgeBase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_bases"

    name: Mapped[str] = mapped_column(String(160), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    visibility: Mapped[str] = mapped_column(String(20), default="users", index=True)
    embedding_model_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("models.id", ondelete="SET NULL")
    )
    rag_chat_model_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("models.id", ondelete="SET NULL"), index=True
    )
    rerank_model_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("models.id", ondelete="SET NULL"), index=True
    )
    rag_max_output_tokens: Mapped[int] = mapped_column(Integer, default=8000)
    wiki_chat_model_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("models.id", ondelete="SET NULL"), index=True
    )
    wiki_health_chat_model_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("models.id", ondelete="SET NULL"), index=True
    )
    wiki_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    wiki_health_check_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    wiki_health_check_interval_hours: Mapped[int] = mapped_column(Integer, default=24)
    wiki_node_types: Mapped[list[str]] = mapped_column(
        ARRAY(String(40)),
        default=lambda: ["主题"],
    )
    wiki_generation_prompt: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT")
    )

    members: Mapped[list[KnowledgeBaseMember]] = relationship(
        back_populates="knowledge_base", cascade="all, delete-orphan"
    )


class KnowledgeBaseMember(Base):
    __tablename__ = "knowledge_base_members"
    __table_args__ = (UniqueConstraint("knowledge_base_id", "user_id", name="uq_kb_member"),)

    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    knowledge_base: Mapped[KnowledgeBase] = relationship(back_populates="members")


document_tag_links = Table(
    "document_tag_links",
    Base.metadata,
    Column(
        "document_id",
        Uuid,
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("tag_id", Uuid, ForeignKey("document_tags.id", ondelete="CASCADE"), primary_key=True),
)


class DocumentTag(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_tags"
    __table_args__ = (
        UniqueConstraint("knowledge_base_id", "name", name="uq_document_tag_kb_name"),
    )

    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    color: Mapped[str | None] = mapped_column(String(20))


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("knowledge_base_id", "sha256", name="uq_document_kb_sha256"),
        Index("ix_documents_kb_source_time", "knowledge_base_id", "source_time"),
        Index("ix_documents_kb_created_at", "knowledge_base_id", "created_at"),
        Index("ix_documents_kb_updated_at", "knowledge_base_id", "updated_at"),
    )

    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(500), index=True)
    filename: Mapped[str] = mapped_column(String(500))
    media_type: Mapped[str] = mapped_column(String(200))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    object_key: Mapped[str] = mapped_column(String(1000), unique=True)
    status: Mapped[str] = mapped_column(String(32), default="uploaded", index=True)
    source_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    parsed_text_key: Mapped[str | None] = mapped_column(String(1000))
    page_count: Mapped[int | None] = mapped_column(Integer)
    parse_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_summary: Mapped[str | None] = mapped_column(String(1000))
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT")
    )

    tags: Mapped[list[DocumentTag]] = relationship(secondary=document_tag_links)


class ProcessingJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "processing_jobs"

    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    job_type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    progress: Mapped[float] = mapped_column(Float, default=0)
    stage: Mapped[str | None] = mapped_column(String(80))
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    external_task_id: Mapped[str | None] = mapped_column(String(200), index=True)
    error_summary: Mapped[str | None] = mapped_column(String(1000))
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Chunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "chunks"
    __table_args__ = (
        Index("ix_chunks_kb_source_time", "knowledge_base_id", "source_time"),
        Index("ix_chunks_kb_created_at", "knowledge_base_id", "created_at"),
        Index("ix_chunks_kb_updated_at", "knowledge_base_id", "updated_at"),
        Index(
            "ix_chunks_search_vector",
            "search_vector",
            postgresql_using="gin",
        ),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    search_text: Mapped[str] = mapped_column(Text)
    search_vector: Mapped[Any] = mapped_column(TSVECTOR)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536))
    token_count: Mapped[int] = mapped_column(Integer)
    page_from: Mapped[int | None] = mapped_column(Integer)
    page_to: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(500))
    source_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)


class ChatSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "chat_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200), default="新对话")
    mode: Mapped[str] = mapped_column(String(20), default="rag")


class ChatMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "chat_messages"

    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("models.id", ondelete="SET NULL")
    )
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    retrieval_params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class MessageCitation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "message_citations"

    message_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_messages.id", ondelete="CASCADE"), index=True
    )
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("chunks.id", ondelete="SET NULL")
    )
    citation_number: Mapped[int] = mapped_column(Integer)
    document_title: Mapped[str] = mapped_column(String(500))
    page_from: Mapped[int | None] = mapped_column(Integer)
    page_to: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(500))
    original_text: Mapped[str] = mapped_column(Text)
    source_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Agent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agents"

    name: Mapped[str] = mapped_column(String(160), unique=True)
    avatar: Mapped[str | None] = mapped_column(String(1000))
    description: Mapped[str] = mapped_column(Text, default="")
    system_prompt: Mapped[str] = mapped_column(Text)
    chat_model_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("models.id", ondelete="RESTRICT")
    )
    visibility: Mapped[str] = mapped_column(String(20), default="users", index=True)
    max_steps: Mapped[int] = mapped_column(Integer, default=8)
    max_tokens: Mapped[int] = mapped_column(Integer, default=12000)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300)
    recommended_questions: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT")
    )


agent_knowledge_bases = Table(
    "agent_knowledge_bases",
    Base.metadata,
    Column("agent_id", Uuid, ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "knowledge_base_id",
        Uuid,
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

agent_users = Table(
    "agent_users",
    Base.metadata,
    Column("agent_id", Uuid, ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)


class AgentRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_runs"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agents.id", ondelete="RESTRICT"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("chat_sessions.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    query: Mapped[str] = mapped_column(Text)
    resolved_time_summary: Mapped[str | None] = mapped_column(Text)
    state_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[str | None] = mapped_column(Text)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    error_summary: Mapped[str | None] = mapped_column(String(1000))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentStep(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_steps"
    __table_args__ = (UniqueConstraint("run_id", "ordinal", name="uq_agent_step_run_ordinal"),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(32))
    summary: Mapped[str | None] = mapped_column(Text)
    tool_name: Mapped[str | None] = mapped_column(String(80))
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_summary: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)


class WikiSpace(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "wiki_spaces"

    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), unique=True
    )
    published_version: Mapped[int | None] = mapped_column(Integer)


class WikiPage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "wiki_pages"
    __table_args__ = (UniqueConstraint("space_id", "slug", name="uq_wiki_page_space_slug"),)

    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("wiki_spaces.id", ondelete="CASCADE"), index=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("wiki_pages.id", ondelete="SET NULL")
    )
    slug: Mapped[str] = mapped_column(String(300))
    title: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    source_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    merged_into_page_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("wiki_pages.id", ondelete="SET NULL"), index=True
    )


class WikiPageVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "wiki_page_versions"
    __table_args__ = (UniqueConstraint("page_id", "version_number", name="uq_wiki_page_version"),)

    page_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("wiki_pages.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    protected_blocks: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    generation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    change_summary: Mapped[str] = mapped_column(Text, default="")
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False)
    source_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)


class WikiPageSource(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "wiki_page_sources"

    page_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("wiki_page_versions.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("chunks.id", ondelete="SET NULL")
    )
    paragraph_key: Mapped[str] = mapped_column(String(120))
    evidence_text: Mapped[str] = mapped_column(Text)
    source_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class WikiNode(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "wiki_nodes"
    __table_args__ = (Index("ix_wiki_nodes_space_source_time", "space_id", "source_time"),)

    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("wiki_spaces.id", ondelete="CASCADE"), index=True
    )
    node_type: Mapped[str] = mapped_column(String(30), index=True)
    label: Mapped[str] = mapped_column(String(500), index=True)
    page_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("wiki_pages.id", ondelete="CASCADE")
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE")
    )
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="SET NULL")
    )
    source_page_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("wiki_pages.id", ondelete="SET NULL")
    )
    source_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))
    embedding_model_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("models.id", ondelete="SET NULL"), index=True
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)


class WikiNodeAlias(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "wiki_node_aliases"
    __table_args__ = (
        UniqueConstraint(
            "space_id",
            "node_id",
            "normalized_alias",
            name="uq_wiki_node_alias_space_node_normalized",
        ),
        Index("ix_wiki_node_alias_space_normalized", "space_id", "normalized_alias"),
    )

    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("wiki_spaces.id", ondelete="CASCADE"), index=True
    )
    node_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("wiki_nodes.id", ondelete="CASCADE"), index=True
    )
    alias: Mapped[str] = mapped_column(String(500))
    normalized_alias: Mapped[str] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(32), default="canonical")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WikiEntityResolution(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "wiki_entity_resolutions"
    __table_args__ = (
        UniqueConstraint(
            "space_id",
            "left_page_id",
            "right_page_id",
            name="uq_wiki_entity_resolution_pair",
        ),
    )

    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("wiki_spaces.id", ondelete="CASCADE"), index=True
    )
    left_page_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("wiki_pages.id", ondelete="CASCADE"), index=True
    )
    right_page_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("wiki_pages.id", ondelete="CASCADE"), index=True
    )
    decision: Mapped[str] = mapped_column(String(20), index=True)
    canonical_page_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("wiki_pages.id", ondelete="SET NULL"), index=True
    )
    reason: Mapped[str] = mapped_column(Text, default="")
    decision_source: Mapped[str] = mapped_column(String(20), default="manual", index=True)
    merge_group_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column("snapshot", JSON, default=dict)
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )


class WikiEdge(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "wiki_edges"
    __table_args__ = (Index("ix_wiki_edges_space_source_time", "space_id", "source_time"),)

    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("wiki_spaces.id", ondelete="CASCADE"), index=True
    )
    source_node_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("wiki_nodes.id", ondelete="CASCADE"), index=True
    )
    target_node_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("wiki_nodes.id", ondelete="CASCADE"), index=True
    )
    edge_type: Mapped[str] = mapped_column(String(40), index=True)
    evidence: Mapped[str] = mapped_column(Text)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="SET NULL")
    )
    source_page_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("wiki_pages.id", ondelete="SET NULL")
    )
    source_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class WikiUpdateJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "wiki_update_jobs"

    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("wiki_spaces.id", ondelete="CASCADE"), index=True
    )
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("models.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    generation_id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True)
    affected_document_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), default=list)
    candidate_version: Mapped[int | None] = mapped_column(Integer)
    quality_report: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    change_summary: Mapped[str | None] = mapped_column(Text)
    error_summary: Mapped[str | None] = mapped_column(String(1000))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WikiHealthJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "wiki_health_jobs"

    space_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("wiki_spaces.id", ondelete="CASCADE"), index=True
    )
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("models.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    trigger: Mapped[str] = mapped_column(String(32), default="manual", index=True)
    auto_repair: Mapped[bool] = mapped_column(Boolean, default=True)
    report: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    proposed_actions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    applied_actions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    error_summary: Mapped[str | None] = mapped_column(String(1000))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_logs"

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(100), index=True)
    resource_type: Mapped[str] = mapped_column(String(80), index=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    request_id: Mapped[str | None] = mapped_column(String(100), index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class SystemSetting(TimestampMixin, Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
