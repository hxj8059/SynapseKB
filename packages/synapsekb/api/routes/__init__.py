from fastapi import APIRouter

from synapsekb.api.routes import (
    agents,
    auth,
    chat_sessions,
    documents,
    health,
    knowledge_bases,
    models,
    operations,
    rag,
    search,
    settings,
    skills,
    tokens,
    users,
    wiki,
)

router = APIRouter()
router.include_router(health.router)
router.include_router(auth.router, prefix="/auth", tags=["认证"])
router.include_router(users.router, prefix="/users", tags=["用户"])
router.include_router(knowledge_bases.router, prefix="/knowledge-bases", tags=["知识库"])
router.include_router(models.router, prefix="/models", tags=["模型"])
router.include_router(settings.router, prefix="/settings", tags=["系统设置"])
router.include_router(operations.router, prefix="/operations", tags=["运维"])
router.include_router(tokens.router, prefix="/tokens", tags=["MCP Token"])
router.include_router(skills.router, prefix="/skills", tags=["Skill"])
router.include_router(documents.router, prefix="/documents", tags=["文档"])
router.include_router(search.router, prefix="/search", tags=["检索"])
router.include_router(rag.router, prefix="/rag", tags=["问答"])
router.include_router(chat_sessions.router, prefix="/chat-sessions", tags=["对话"])
router.include_router(agents.router, prefix="/agents", tags=["Agent"])
router.include_router(wiki.router, prefix="/wiki", tags=["Wiki"])
