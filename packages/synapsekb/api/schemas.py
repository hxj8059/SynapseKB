from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    HttpUrl,
    field_validator,
)

from synapsekb.domain.enums import DEFAULT_MCP_SCOPES, McpScope, ModelKind, TimeField


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserRead(ORMModel):
    id: uuid.UUID
    email: EmailStr
    display_name: str
    role: str
    is_active: bool
    timezone: str
    created_at: datetime


class UserCreate(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=256)
    role: str = "user"
    timezone: str = "Asia/Shanghai"

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        if value not in {"admin", "user"}:
            raise ValueError("role must be admin or user")
        return value


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    password: str | None = Field(default=None, min_length=12, max_length=256)
    role: str | None = None
    is_active: bool | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator("role")
    @classmethod
    def validate_optional_role(cls, value: str | None) -> str | None:
        if value is not None and value not in {"admin", "user"}:
            raise ValueError("role must be admin or user")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserRead


def _normalize_wiki_node_types(value: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        label = item.strip()
        if not label:
            raise ValueError("Wiki 节点类型不能为空")
        if len(label) > 30:
            raise ValueError("Wiki 节点类型不能超过 30 个字符")
        if any(character in label for character in ("\n", "\r", "\t")):
            raise ValueError("Wiki 节点类型不能包含控制字符")
        key = label.casefold()
        if key not in seen:
            normalized.append(label)
            seen.add(key)
    if not normalized:
        raise ValueError("至少配置一种 Wiki 节点类型")
    return normalized


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=5000)
    visibility: str = "users"
    member_ids: list[uuid.UUID] = Field(default_factory=list)
    embedding_model_id: uuid.UUID | None = None
    rag_chat_model_id: uuid.UUID | None = None
    rerank_model_id: uuid.UUID | None = None
    rag_max_output_tokens: int = Field(default=8000, ge=1000, le=32_000)
    wiki_chat_model_id: uuid.UUID | None = None
    wiki_health_chat_model_id: uuid.UUID | None = None
    wiki_enabled: bool = True
    wiki_health_check_enabled: bool = True
    wiki_health_check_interval_hours: int = Field(default=24, ge=1, le=24 * 30)
    wiki_node_types: list[str] = Field(
        default_factory=lambda: ["产业主题", "个股"],
        min_length=1,
        max_length=12,
    )
    wiki_generation_prompt: str = Field(default="", max_length=8000)

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, value: str) -> str:
        if value not in {"all", "users"}:
            raise ValueError("visibility must be all or users")
        return value

    @field_validator("wiki_node_types")
    @classmethod
    def validate_wiki_node_types(cls, value: list[str]) -> list[str]:
        return _normalize_wiki_node_types(value)


class KnowledgeBaseRead(ORMModel):
    id: uuid.UUID
    name: str
    description: str
    visibility: str
    embedding_model_id: uuid.UUID | None
    rag_chat_model_id: uuid.UUID | None
    rerank_model_id: uuid.UUID | None
    rag_max_output_tokens: int
    wiki_chat_model_id: uuid.UUID | None
    wiki_health_chat_model_id: uuid.UUID | None
    wiki_enabled: bool
    wiki_health_check_enabled: bool
    wiki_health_check_interval_hours: int
    wiki_node_types: list[str]
    wiki_generation_prompt: str
    created_at: datetime
    updated_at: datetime


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=5000)
    visibility: str | None = None
    member_ids: list[uuid.UUID] | None = Field(default=None, max_length=500)
    embedding_model_id: uuid.UUID | None = None
    rag_chat_model_id: uuid.UUID | None = None
    rerank_model_id: uuid.UUID | None = None
    rag_max_output_tokens: int | None = Field(default=None, ge=1000, le=32_000)
    wiki_chat_model_id: uuid.UUID | None = None
    wiki_health_chat_model_id: uuid.UUID | None = None
    wiki_enabled: bool | None = None
    wiki_health_check_enabled: bool | None = None
    wiki_health_check_interval_hours: int | None = Field(default=None, ge=1, le=24 * 30)
    wiki_node_types: list[str] | None = Field(default=None, min_length=1, max_length=12)
    wiki_generation_prompt: str | None = Field(default=None, max_length=8000)

    @field_validator("visibility")
    @classmethod
    def validate_optional_visibility(cls, value: str | None) -> str | None:
        if value is not None and value not in {"all", "users"}:
            raise ValueError("visibility must be all or users")
        return value

    @field_validator("wiki_node_types")
    @classmethod
    def validate_optional_wiki_node_types(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_wiki_node_types(value) if value is not None else None


class ModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: ModelKind
    provider: str = Field(min_length=1, max_length=32)
    base_url: HttpUrl
    model_name: str = Field(min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=1000)
    timeout_seconds: int = Field(default=60, ge=1, le=600)
    max_concurrency: int = Field(default=5, ge=1, le=100)
    embedding_dimensions: int | None = Field(default=None, ge=1, le=20000)
    config: dict[str, Any] = Field(default_factory=dict)


class ModelRead(ORMModel):
    id: uuid.UUID
    name: str
    kind: str
    provider: str
    base_url: str
    model_name: str
    timeout_seconds: int
    max_concurrency: int
    embedding_dimensions: int | None
    config: dict[str, Any]
    is_enabled: bool
    has_api_key: bool = False
    created_at: datetime
    updated_at: datetime


class ModelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    base_url: HttpUrl | None = None
    model_name: str | None = Field(default=None, min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=1000)
    clear_api_key: bool = False
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)
    max_concurrency: int | None = Field(default=None, ge=1, le=100)
    embedding_dimensions: int | None = Field(default=None, ge=1, le=20000)
    is_enabled: bool | None = None
    config: dict[str, Any] | None = None


class ModelTestResponse(BaseModel):
    ok: bool
    kind: str
    latency_ms: int
    details: dict[str, Any]


class OcrSettingsRead(BaseModel):
    base_url: str | None
    default_model: str
    timeout_seconds: int
    max_concurrency: int
    has_api_key: bool
    source: str


class OcrSettingsUpdate(BaseModel):
    base_url: HttpUrl | None = None
    api_key: str | None = Field(default=None, max_length=1000)
    clear_api_key: bool = False
    default_model: str = Field(default="PaddleOCR-VL-1.6", max_length=100)
    timeout_seconds: int = Field(default=600, ge=10, le=1800)
    max_concurrency: int = Field(default=2, ge=1, le=20)

    @field_validator("default_model")
    @classmethod
    def validate_ocr_model(cls, value: str) -> str:
        allowed = {"PP-OCRv6", "PaddleOCR-VL-1.6", "PP-StructureV3"}
        if value not in allowed:
            raise ValueError("unsupported PaddleOCR model")
        return value


class OcrTestResponse(BaseModel):
    ok: bool
    task_id: str
    page_count: int
    markdown_preview: str
    metadata: dict[str, Any]


class StorageSettingsRead(BaseModel):
    backend: Literal["local", "s3", "oss", "cos"]
    local_storage_path: str
    bucket: str
    endpoint: str | None
    internal_endpoint: str | None
    use_internal_endpoint: bool
    region: str
    force_path_style: bool
    key_prefix: str
    has_access_key: bool
    has_secret_key: bool
    source: str


class StorageSettingsUpdate(BaseModel):
    backend: Literal["local", "s3", "oss", "cos"] = "oss"
    local_storage_path: str = Field(default="./data/storage", min_length=1, max_length=500)
    bucket: str = Field(default="", max_length=200)
    endpoint: HttpUrl | None = None
    internal_endpoint: HttpUrl | None = None
    use_internal_endpoint: bool = False
    region: str = Field(default="auto", min_length=1, max_length=100)
    force_path_style: bool = False
    key_prefix: str = Field(default="", max_length=500)
    access_key: str | None = Field(default=None, max_length=1000)
    secret_key: str | None = Field(default=None, max_length=2000)
    clear_access_key: bool = False
    clear_secret_key: bool = False

    @field_validator("key_prefix")
    @classmethod
    def validate_key_prefix(cls, value: str) -> str:
        clean = value.strip("/")
        if ".." in clean.split("/"):
            raise ValueError("key_prefix 不能包含 ..")
        return clean


class StorageTestResponse(BaseModel):
    ok: bool
    backend: str
    bucket: str
    latency_ms: int
    presigned_upload_supported: bool


class PersonalAccessTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: set[McpScope] = Field(
        default_factory=lambda: set(DEFAULT_MCP_SCOPES),
        min_length=1,
    )
    expires_at: AwareDatetime | None = None


class PersonalAccessTokenCreated(BaseModel):
    id: uuid.UUID
    name: str
    token: str
    scopes: list[str]
    expires_at: datetime | None


class PersonalAccessTokenRead(ORMModel):
    id: uuid.UUID
    name: str
    token_prefix: str
    scopes: list[str]
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


class TimeFilter(BaseModel):
    field: TimeField = TimeField.SOURCE_TIME
    from_: AwareDatetime | None = Field(default=None, alias="from")
    to: AwareDatetime | None = None
    include_unknown: bool = False

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("to")
    @classmethod
    def validate_to(cls, value: datetime | None, info: Any) -> datetime | None:
        start = info.data.get("from_")
        if start is not None and value is not None and value < start:
            raise ValueError("time_filter.to must be after from")
        return value


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    knowledge_base_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    tag_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    time_filter: TimeFilter | None = None
    top_k: int = Field(default=20, ge=1, le=100)


class CitationRead(BaseModel):
    citation_number: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    page_from: int | None
    page_to: int | None
    section: str | None
    original_text: str
    source_time: datetime | None
    score: float


class SearchResponse(BaseModel):
    query: str
    time_filter: TimeFilter | None
    results: list[CitationRead]


class RagRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    session_id: uuid.UUID | None = None
    knowledge_base_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    tag_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    time_filter: TimeFilter | None = None
    top_k: int = Field(default=12, ge=1, le=50)
    chat_model_id: uuid.UUID | None = None


class ChatSessionRead(ORMModel):
    id: uuid.UUID
    title: str
    mode: str
    created_at: datetime
    updated_at: datetime


class ChatSessionUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ChatCitationRead(ORMModel):
    citation_number: int
    chunk_id: uuid.UUID | None
    document_id: uuid.UUID | None
    document_title: str
    page_from: int | None
    page_to: int | None
    section: str | None
    original_text: str
    source_time: datetime | None


class ChatMessageRead(ORMModel):
    id: uuid.UUID
    role: str
    content: str
    model_id: uuid.UUID | None
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int | None
    retrieval_params: dict[str, Any]
    created_at: datetime
    citations: list[ChatCitationRead] = Field(default_factory=list)


class ChatSessionDetail(ChatSessionRead):
    messages: list[ChatMessageRead]


class DocumentRead(ORMModel):
    id: uuid.UUID
    knowledge_base_id: uuid.UUID
    title: str
    filename: str
    media_type: str
    size_bytes: int
    sha256: str
    status: str
    source_time: datetime | None
    page_count: int | None
    error_summary: str | None
    created_at: datetime
    updated_at: datetime


class ProcessingJobRead(ORMModel):
    id: uuid.UUID
    document_id: uuid.UUID
    job_type: str
    status: str
    progress: float
    stage: str | None
    attempt: int
    error_summary: str | None
    created_at: datetime
    updated_at: datetime


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    avatar: str | None = Field(default=None, max_length=1000)
    description: str = Field(default="", max_length=5000)
    system_prompt: str = Field(min_length=1, max_length=30_000)
    chat_model_id: uuid.UUID
    visibility: str = "users"
    knowledge_base_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    user_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    max_steps: int = Field(default=8, ge=1, le=20)
    max_tokens: int = Field(default=12_000, ge=1000, le=100_000)
    timeout_seconds: int = Field(default=300, ge=30, le=900)
    recommended_questions: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("visibility")
    @classmethod
    def validate_agent_visibility(cls, value: str) -> str:
        if value not in {"all", "users"}:
            raise ValueError("visibility must be all or users")
        return value


class AgentRead(ORMModel):
    id: uuid.UUID
    name: str
    avatar: str | None
    description: str
    system_prompt: str
    chat_model_id: uuid.UUID
    visibility: str
    max_steps: int
    max_tokens: int
    timeout_seconds: int
    recommended_questions: list[str]
    is_enabled: bool
    created_at: datetime
    updated_at: datetime


class AgentRuntimeUpdate(BaseModel):
    chat_model_id: uuid.UUID
    max_steps: int = Field(ge=1, le=20)
    max_tokens: int = Field(ge=4000, le=32_000)
    timeout_seconds: int = Field(ge=30, le=900)


class AgentRunCreate(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    session_id: uuid.UUID | None = None


class AgentCitationRead(BaseModel):
    citation_number: int
    chunk_id: uuid.UUID | None = None
    document_id: uuid.UUID
    document_name: str
    page_from: int | None = None
    page_to: int | None = None
    section: str | None = None
    original_text: str
    source_time: datetime | None = None
    score: float | None = None


class AgentRunRead(ORMModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    user_id: uuid.UUID
    session_id: uuid.UUID | None
    status: str
    query: str
    resolved_time_summary: str | None
    result: str | None
    citations: list[AgentCitationRead] = Field(default_factory=list)
    error_summary: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WikiPageRead(ORMModel):
    id: uuid.UUID
    space_id: uuid.UUID
    parent_id: uuid.UUID | None
    slug: str
    title: str
    summary: str
    sort_order: int
    source_time: datetime | None
    current_version_id: uuid.UUID | None
    is_archived: bool
    merged_into_page_id: uuid.UUID | None
    node_type: str | None = None
    created_at: datetime
    updated_at: datetime


class WikiPageSourceRead(ORMModel):
    document_id: uuid.UUID
    document_name: str | None = None
    chunk_id: uuid.UUID | None
    paragraph_key: str
    evidence_text: str
    source_time: datetime | None


class WikiPageContent(WikiPageRead):
    content: str
    version_number: int
    protected_blocks: list[str]
    sources: list[WikiPageSourceRead]


class WikiPageEdit(BaseModel):
    content: str = Field(min_length=1, max_length=500_000)
    protected_blocks: list[str] = Field(default_factory=list, max_length=100)
    change_summary: str = Field(default="手动编辑", max_length=1000)
    source_time: AwareDatetime | None = None


class WikiPageVersionRead(ORMModel):
    id: uuid.UUID
    page_id: uuid.UUID
    version_number: int
    content: str
    protected_blocks: list[str]
    change_summary: str
    is_manual: bool
    source_time: datetime | None
    created_at: datetime
    updated_at: datetime


class WikiGenerateRequest(BaseModel):
    knowledge_base_id: uuid.UUID
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10_000)


class WikiGraphSearchRequest(BaseModel):
    query: str = Field(default="", max_length=500)
    mode: Literal["local", "overview"] = "local"
    # None keeps backward-compatible "all types" semantics for callers that
    # omit the field. An explicit empty list means "show no node types".
    node_types: list[str] | None = Field(default=None, max_length=20)
    time_filter: TimeFilter | None = None
    limit: int = Field(default=50, ge=1, le=300)


class WikiJobRead(ORMModel):
    id: uuid.UUID
    space_id: uuid.UUID
    model_id: uuid.UUID | None
    status: str
    generation_id: uuid.UUID
    affected_document_ids: list[uuid.UUID]
    candidate_version: int | None
    quality_report: dict[str, Any]
    change_summary: str | None
    error_summary: str | None
    created_at: datetime
    updated_at: datetime


class WikiHealthStartRequest(BaseModel):
    knowledge_base_id: uuid.UUID
    auto_repair: bool = True


class WikiHealthJobRead(ORMModel):
    id: uuid.UUID
    space_id: uuid.UUID
    model_id: uuid.UUID | None
    status: str
    trigger: str
    auto_repair: bool
    report: dict[str, Any]
    proposed_actions: list[dict[str, Any]]
    applied_actions: list[dict[str, Any]]
    error_summary: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WikiMergePagesRequest(BaseModel):
    target_page_id: uuid.UUID
    source_page_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)
    change_summary: str = Field(default="合并相似 Wiki 节点", max_length=1000)
    health_job_id: uuid.UUID | None = None


class WikiEntityDecisionRequest(BaseModel):
    left_page_id: uuid.UUID
    right_page_id: uuid.UUID
    decision: Literal["distinct"] = "distinct"
    reason: str = Field(default="管理员确认不是同一节点", max_length=1000)
    health_job_id: uuid.UUID | None = None


class WikiAddRelationRequest(BaseModel):
    source_page_id: uuid.UUID
    target_page_id: uuid.UUID
    relation_type: str = Field(default="related_to", min_length=1, max_length=40)
    evidence: str = Field(min_length=1, max_length=4000)
    health_job_id: uuid.UUID | None = None
    proposal_id: uuid.UUID | None = None


class UploadInitRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=500)
    media_type: str = Field(min_length=1, max_length=200)
    size_bytes: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    title: str | None = Field(default=None, max_length=500)
    source_time: AwareDatetime | None = None


class UploadInitResponse(BaseModel):
    document: DocumentRead
    upload_url: str | None
    method: str
    expires_in: int | None = None


class UploadCompleteRequest(BaseModel):
    document_id: uuid.UUID


class UrlImportRequest(BaseModel):
    knowledge_base_id: uuid.UUID
    url: HttpUrl
    title: str | None = Field(default=None, min_length=1, max_length=500)
    source_time: AwareDatetime | None = None


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    source_time: AwareDatetime | None = None
    tag_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)


class DocumentTagCreate(BaseModel):
    knowledge_base_id: uuid.UUID
    name: str = Field(min_length=1, max_length=80)
    color: str | None = Field(default=None, max_length=20)


class DocumentTagRead(ORMModel):
    id: uuid.UUID
    knowledge_base_id: uuid.UUID
    name: str
    color: str | None
    created_at: datetime
    updated_at: datetime


class ChunkRead(ORMModel):
    id: uuid.UUID
    ordinal: int
    content: str
    token_count: int
    page_from: int | None
    page_to: int | None
    section: str | None
    source_time: datetime | None
    created_at: datetime
    updated_at: datetime


class OperationTaskRead(BaseModel):
    id: uuid.UUID
    task_type: str
    resource_id: uuid.UUID
    status: str
    stage: str | None
    progress: float | None
    model_id: uuid.UUID | None = None
    model_name: str | None = None
    summary: str | None = None
    error_summary: str | None
    created_at: datetime
    updated_at: datetime


class AuditLogRead(ORMModel):
    id: uuid.UUID
    actor_user_id: uuid.UUID | None
    action: str
    resource_type: str
    resource_id: uuid.UUID | None
    request_id: str | None
    ip_address: str | None
    metadata_json: dict[str, Any]
    created_at: datetime
