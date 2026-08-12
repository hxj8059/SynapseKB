from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "admin"
    USER = "user"


class Visibility(StrEnum):
    ALL = "all"
    USERS = "users"


class ModelKind(StrEnum):
    CHAT = "chat"
    EMBEDDING = "embedding"
    RERANK = "rerank"
    OCR = "ocr"


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TimeField(StrEnum):
    SOURCE_TIME = "source_time"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


class McpScope(StrEnum):
    KB_READ = "kb:read"
    DOCUMENT_READ = "document:read"
    DOCUMENT_WRITE = "document:write"
    SEARCH_READ = "search:read"
    AGENT_RUN = "agent:run"
    WIKI_READ = "wiki:read"
    WIKI_ADMIN = "wiki:admin"


DEFAULT_MCP_SCOPES = frozenset(
    {
        McpScope.KB_READ,
        McpScope.DOCUMENT_READ,
        McpScope.SEARCH_READ,
        McpScope.AGENT_RUN,
        McpScope.WIKI_READ,
    }
)
