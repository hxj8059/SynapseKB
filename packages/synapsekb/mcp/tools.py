from __future__ import annotations

import base64
import hashlib
import tempfile
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy import ColumnElement, and_, exists, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from apps.agent_runner.actors import execute_agent_run
from apps.document_worker.actors import process_document
from synapsekb.agent.tools import AgentToolContext, execute_tool
from synapsekb.api.schemas import CitationRead, TimeFilter
from synapsekb.auth.policy import (
    knowledge_base_access_clause,
    require_knowledge_base_access,
)
from synapsekb.config import get_settings
from synapsekb.database.models import (
    Agent,
    AgentRun,
    AuditLog,
    Document,
    KnowledgeBase,
    ProcessingJob,
    ProviderModel,
    User,
    WikiEdge,
    WikiNode,
    WikiPage,
    WikiPageSource,
    WikiPageVersion,
    WikiSpace,
    agent_users,
)
from synapsekb.database.session import AsyncSessionFactory
from synapsekb.document_processing.validation import validate_upload
from synapsekb.mcp.auth import McpPrincipal, principal_var
from synapsekb.models.provider import DeterministicMockProvider, create_provider
from synapsekb.retrieval.context import build_citation_context
from synapsekb.storage.factory import create_runtime_storage

settings = get_settings()

mcp = FastMCP(
    "SynapseKB",
    instructions=(
        "私有知识库 MCP。时间条件必须使用结构化字段；默认 source_time；"
        "跨时期比较必须分别检索；回答必须保留引用。"
    ),
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
    host="0.0.0.0",  # noqa: S104 - exposed only through the Nginx service network
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=settings.mcp_transport_allowed_hosts,
        allowed_origins=settings.mcp_transport_allowed_origins,
    ),
)


@asynccontextmanager
async def tool_session(
    scope: str,
    tool_name: str,
) -> AsyncIterator[tuple[AsyncSession, User, McpPrincipal]]:
    principal = principal_var.get()
    if principal is None:
        raise PermissionError("MCP 请求未认证")
    if scope not in principal.scopes:
        raise PermissionError(f"Token 缺少 Scope: {scope}")
    async with AsyncSessionFactory() as session:
        user = await session.get(User, principal.user_id)
        if user is None or not user.is_active:
            raise PermissionError("用户不可用")
        succeeded = False
        try:
            yield session, user, principal
            succeeded = True
        except Exception:
            await session.rollback()
            raise
        finally:
            session.add(
                AuditLog(
                    actor_user_id=principal.user_id,
                    action=f"mcp.{tool_name}",
                    resource_type="mcp_tool",
                    resource_id=principal.token_id,
                    metadata_json={
                        "scope": scope,
                        "outcome": "succeeded" if succeeded else "failed",
                    },
                    created_at=datetime.now(UTC),
                )
            )
            await session.commit()


def _serialize_kb(item: KnowledgeBase) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "name": item.name,
        "description": item.description,
        "visibility": item.visibility,
        "wiki_enabled": item.wiki_enabled,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


def _serialize_document(item: Document) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "knowledge_base_id": str(item.knowledge_base_id),
        "title": item.title,
        "filename": item.filename,
        "media_type": item.media_type,
        "size_bytes": item.size_bytes,
        "status": item.status,
        "source_time": item.source_time.isoformat() if item.source_time else None,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


async def _validated_kbs(
    session: AsyncSession,
    user: User,
    ids: list[str],
) -> list[uuid.UUID]:
    parsed = [uuid.UUID(item) for item in ids]
    for item in set(parsed):
        await require_knowledge_base_access(session, user, item)
    return parsed


def _filter(
    field: str = "source_time",
    from_time: str | None = None,
    to_time: str | None = None,
    include_unknown: bool = False,
) -> dict[str, Any] | None:
    if not from_time and not to_time:
        return None
    return TimeFilter.model_validate(
        {
            "field": field,
            "from": from_time,
            "to": to_time,
            "include_unknown": include_unknown,
        }
    ).model_dump(mode="json", by_alias=True)


@mcp.tool()
async def kb_list() -> list[dict[str, Any]]:
    """列出当前用户有权访问的知识库。"""
    async with tool_session("kb:read", "kb_list") as (session, user, _):
        items = (
            await session.scalars(
                select(KnowledgeBase)
                .where(knowledge_base_access_clause(user))
                .order_by(KnowledgeBase.name)
            )
        ).all()
        return [_serialize_kb(item) for item in items]


@mcp.tool()
async def kb_get(knowledge_base_id: str) -> dict[str, Any]:
    """读取一个授权知识库。"""
    async with tool_session("kb:read", "kb_get") as (session, user, _):
        item = await require_knowledge_base_access(session, user, uuid.UUID(knowledge_base_id))
        return _serialize_kb(item)


@mcp.tool()
async def document_list(
    knowledge_base_id: str,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """分页列出知识库文档。"""
    async with tool_session("document:read", "document_list") as (session, user, _):
        kb_id = uuid.UUID(knowledge_base_id)
        await require_knowledge_base_access(session, user, kb_id)
        query = select(Document).where(Document.knowledge_base_id == kb_id)
        if status:
            query = query.where(Document.status == status)
        items = (
            await session.scalars(
                query.order_by(Document.updated_at.desc(), Document.id)
                .offset(max(offset, 0))
                .limit(min(max(limit, 1), 500))
            )
        ).all()
        return [_serialize_document(item) for item in items]


@mcp.tool()
async def document_get(document_id: str) -> dict[str, Any]:
    """读取文档元数据。"""
    async with tool_session("document:read", "document_get") as (session, user, _):
        document = await session.get(Document, uuid.UUID(document_id))
        if document is None:
            raise ValueError("文档不存在")
        await require_knowledge_base_access(session, user, document.knowledge_base_id)
        return _serialize_document(document)


@mcp.tool()
async def document_download(document_id: str) -> dict[str, Any]:
    """获取临时下载 URL; 本地开发存储返回小文件 base64。"""
    async with tool_session("document:read", "document_download") as (session, user, _):
        document = await session.get(Document, uuid.UUID(document_id))
        if document is None:
            raise ValueError("文档不存在")
        await require_knowledge_base_access(session, user, document.knowledge_base_id)
        storage = await create_runtime_storage(session)
        url = await storage.presign_download(document.object_key, 300)
        if url:
            return {"download_url": url, "expires_in": 300}
        if document.size_bytes > 10 * 1024 * 1024:
            raise ValueError("本地开发存储仅允许通过 MCP 下载 10MB 以下文件")
        content = await storage.read(document.object_key)
        return {
            "filename": document.filename,
            "media_type": document.media_type,
            "content_base64": base64.b64encode(content).decode(),
        }


@mcp.tool()
async def document_upload(
    knowledge_base_id: str,
    filename: str,
    media_type: str,
    content_base64: str,
    source_time: str | None = None,
) -> dict[str, Any]:
    """上传 10MB 以下文档。该写操作需要 document:write 且 App 管理员权限。"""
    async with tool_session("document:write", "document_upload") as (session, user, _):
        kb_id = uuid.UUID(knowledge_base_id)
        await require_knowledge_base_access(session, user, kb_id, write=True)
        try:
            content = base64.b64decode(content_base64, validate=True)
        except ValueError as exc:
            raise ValueError("content_base64 无效") from exc
        if not content or len(content) > 10 * 1024 * 1024:
            raise ValueError("MCP 上传限制为 1 字节到 10MB")
        safe_name = validate_upload(filename, media_type, content[:32])
        sha256 = hashlib.sha256(content).hexdigest()
        duplicate = await session.scalar(
            select(Document).where(
                Document.knowledge_base_id == kb_id,
                Document.sha256 == sha256,
            )
        )
        if duplicate is not None:
            raise ValueError(f"相同文件已存在: {duplicate.id}")
        parsed_source_time = (
            datetime.fromisoformat(source_time) if source_time is not None else None
        )
        if parsed_source_time is not None and parsed_source_time.utcoffset() is None:
            raise ValueError("source_time 必须包含时区")
        document = Document(
            knowledge_base_id=kb_id,
            title=Path(safe_name).stem,
            filename=safe_name,
            media_type=media_type,
            size_bytes=len(content),
            sha256=sha256,
            object_key="pending",
            status="uploaded",
            source_time=parsed_source_time,
            created_by_id=user.id,
        )
        session.add(document)
        await session.flush()
        document.object_key = f"originals/{kb_id}/{document.id}/{safe_name}"
        with tempfile.NamedTemporaryFile(prefix="synapsekb-mcp-", delete=False) as handle:
            path = Path(handle.name)
            handle.write(content)
        try:
            storage = await create_runtime_storage(session)
            await storage.put_file(document.object_key, path, media_type)
        finally:
            path.unlink(missing_ok=True)
        job = ProcessingJob(
            document_id=document.id,
            job_type="parse",
            status="queued",
            idempotency_key=f"document:{document.id}:mcp",
            progress=0,
            stage="queued",
        )
        session.add(job)
        document.status = "queued"
        await session.commit()
        process_document.send(str(job.id))
        return _serialize_document(document)


async def _search_tool(
    session: AsyncSession,
    user: User,
    query: str,
    knowledge_base_ids: list[str],
    document_ids: list[str],
    tag_ids: list[str],
    field: str,
    from_time: str | None,
    to_time: str | None,
    include_unknown: bool,
    top_k: int,
) -> dict[str, Any]:
    ids = await _validated_kbs(session, user, knowledge_base_ids)
    return await execute_tool(
        "knowledge_search",
        {
            "query": query,
            "document_ids": document_ids,
            "tag_ids": tag_ids,
            "time_filter": _filter(field, from_time, to_time, include_unknown),
            "top_k": top_k,
        },
        AgentToolContext(session, user, ids),
    )


@mcp.tool()
async def knowledge_search(
    query: str,
    knowledge_base_ids: list[str],
    document_ids: list[str] | None = None,
    tag_ids: list[str] | None = None,
    field: str = "source_time",
    from_time: str | None = None,
    to_time: str | None = None,
    include_unknown: bool = False,
    top_k: int = 20,
) -> dict[str, Any]:
    """执行带结构化时间条件的混合检索并返回引用。"""
    async with tool_session("search:read", "knowledge_search") as (session, user, _):
        return await _search_tool(
            session,
            user,
            query,
            knowledge_base_ids,
            document_ids or [],
            tag_ids or [],
            field,
            from_time,
            to_time,
            include_unknown,
            top_k,
        )


@mcp.tool()
async def timeline_search(
    query: str,
    knowledge_base_ids: list[str],
    from_time: str,
    to_time: str,
    document_ids: list[str] | None = None,
    tag_ids: list[str] | None = None,
    field: str = "source_time",
    include_unknown: bool = False,
    top_k: int = 20,
) -> dict[str, Any]:
    """按必填时间范围检索。"""
    async with tool_session("search:read", "timeline_search") as (session, user, _):
        return await _search_tool(
            session,
            user,
            query,
            knowledge_base_ids,
            document_ids or [],
            tag_ids or [],
            field,
            from_time,
            to_time,
            include_unknown,
            top_k,
        )


@mcp.tool()
async def compare_periods(
    query: str,
    knowledge_base_ids: list[str],
    period_a_from: str,
    period_a_to: str,
    period_b_from: str,
    period_b_to: str,
    document_ids: list[str] | None = None,
    tag_ids: list[str] | None = None,
    field: str = "source_time",
    top_k: int = 12,
) -> dict[str, Any]:
    """分别检索两个时期并返回可比较的两组引用。"""
    async with tool_session("search:read", "compare_periods") as (session, user, _):
        ids = await _validated_kbs(session, user, knowledge_base_ids)
        return await execute_tool(
            "compare_periods",
            {
                "query": query,
                "document_ids": document_ids or [],
                "tag_ids": tag_ids or [],
                "period_a": _filter(field, period_a_from, period_a_to, False),
                "period_b": _filter(field, period_b_from, period_b_to, False),
                "top_k": top_k,
            },
            AgentToolContext(session, user, ids),
        )


@mcp.tool()
async def rag_answer(
    query: str,
    knowledge_base_ids: list[str],
    document_ids: list[str] | None = None,
    tag_ids: list[str] | None = None,
    field: str = "source_time",
    from_time: str | None = None,
    to_time: str | None = None,
    include_unknown: bool = False,
    top_k: int = 12,
) -> dict[str, Any]:
    """检索后由 Chat 模型生成带编号引用的答案。"""
    async with tool_session("search:read", "rag_answer") as (session, user, _):
        result = await _search_tool(
            session,
            user,
            query,
            knowledge_base_ids,
            document_ids or [],
            tag_ids or [],
            field,
            from_time,
            to_time,
            include_unknown,
            top_k,
        )
        kb_ids = [uuid.UUID(item) for item in knowledge_base_ids]
        knowledge_bases = list(
            (
                await session.scalars(
                    select(KnowledgeBase).where(KnowledgeBase.id.in_(kb_ids))
                )
            ).all()
        )
        model_ids = {item.rag_chat_model_id for item in knowledge_bases}
        if len(model_ids) > 1:
            raise ValueError("所选知识库的 RAG Chat 模型不一致")
        model_id = next(iter(model_ids), None)
        model = await session.get(ProviderModel, model_id) if model_id else None
        if model is None:
            available = list(
                (
                    await session.scalars(
                        select(ProviderModel)
                        .where(
                            ProviderModel.kind == "chat",
                            ProviderModel.is_enabled.is_(True),
                        )
                        .order_by(ProviderModel.created_at, ProviderModel.id)
                        .limit(2)
                    )
                ).all()
            )
            if len(available) > 1:
                raise ValueError("存在多个 Chat 模型，请配置知识库的 RAG Chat 模型")
            model = available[0] if available else None
        if model is None:
            raise ValueError("尚未配置 Chat 模型")
        max_output_tokens = min(item.rag_max_output_tokens for item in knowledge_bases)
        provider = create_provider(model)
        if isinstance(provider, DeterministicMockProvider):
            await provider.close()
            raise ValueError("Mock Provider 不支持 RAG")
        citations = result["citations"]
        context = await build_citation_context(
            session,
            [CitationRead.model_validate(item) for item in citations],
        )
        parts: list[str] = []
        try:
            async for delta in provider.chat_stream(
                [
                    {
                        "role": "system",
                        "content": "仅依据材料回答，关键结论使用 [编号] 引用。",
                    },
                    {"role": "user", "content": f"问题：{query}\n\n材料：\n{context}"},
                ],
                max_tokens=max_output_tokens,
            ):
                parts.append(delta)
            if provider.last_chat_finish_reason == "length":
                raise RuntimeError(
                    f"RAG 回答达到输出上限（{max_output_tokens} Token），未返回截断结果"
                )
        finally:
            await provider.close()
        return {"answer": "".join(parts), "citations": citations}


def _agent_access_clause(user: User) -> ColumnElement[bool]:
    if user.role == "admin":
        return true()
    return and_(
        Agent.is_enabled.is_(True),
        or_(
            Agent.visibility == "all",
            exists(
                select(agent_users.c.user_id).where(
                    agent_users.c.agent_id == Agent.id,
                    agent_users.c.user_id == user.id,
                )
            ),
        ),
    )


@mcp.tool()
async def agent_list() -> list[dict[str, Any]]:
    """列出授权 Agent。"""
    async with tool_session("agent:run", "agent_list") as (session, user, _):
        agents = (await session.scalars(select(Agent).where(_agent_access_clause(user)))).all()
        return [
            {"id": str(item.id), "name": item.name, "description": item.description}
            for item in agents
        ]


@mcp.tool()
async def agent_run_start(agent_id: str, query: str) -> dict[str, Any]:
    """启动长 Agent 任务, 立即返回 run_id。"""
    async with tool_session("agent:run", "agent_run_start") as (session, user, _):
        agent = await session.scalar(
            select(Agent).where(
                Agent.id == uuid.UUID(agent_id),
                _agent_access_clause(user),
            )
        )
        if agent is None:
            raise ValueError("Agent 不存在或无权访问")
        run = AgentRun(agent_id=agent.id, user_id=user.id, status="queued", query=query)
        session.add(run)
        await session.commit()
        execute_agent_run.send(str(run.id))
        return {"run_id": str(run.id), "status": run.status}


async def _owned_run(session: AsyncSession, user: User, run_id: str) -> AgentRun:
    clauses = [AgentRun.id == uuid.UUID(run_id)]
    if user.role != "admin":
        clauses.append(AgentRun.user_id == user.id)
    run = await session.scalar(select(AgentRun).where(*clauses))
    if run is None:
        raise ValueError("Agent 运行不存在")
    return run


@mcp.tool()
async def agent_run_get(run_id: str) -> dict[str, Any]:
    """查询 Agent 运行状态和结果。"""
    async with tool_session("agent:run", "agent_run_get") as (session, user, _):
        run = await _owned_run(session, user, run_id)
        return {
            "run_id": str(run.id),
            "status": run.status,
            "time_summary": run.resolved_time_summary,
            "result": run.result,
            "citations": run.citations,
            "error_summary": run.error_summary,
        }


@mcp.tool()
async def agent_run_cancel(run_id: str) -> dict[str, Any]:
    """取消尚未结束的 Agent 运行。"""
    async with tool_session("agent:run", "agent_run_cancel") as (session, user, _):
        run = await _owned_run(session, user, run_id)
        if run.status in {"queued", "running"}:
            run.cancel_requested_at = datetime.now(UTC)
            await session.commit()
        return {"run_id": str(run.id), "status": run.status, "cancel_requested": True}


async def _wiki_space(
    session: AsyncSession,
    user: User,
    knowledge_base_id: str,
) -> WikiSpace:
    kb_id = uuid.UUID(knowledge_base_id)
    await require_knowledge_base_access(session, user, kb_id)
    space = await session.scalar(
        select(WikiSpace).where(
            WikiSpace.knowledge_base_id == kb_id,
            WikiSpace.published_version.is_not(None),
        )
    )
    if space is None:
        raise ValueError("Wiki 尚未发布")
    return space


def _wiki_page(item: WikiPage) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "title": item.title,
        "summary": item.summary,
        "parent_id": str(item.parent_id) if item.parent_id else None,
        "source_time": item.source_time.isoformat() if item.source_time else None,
    }


@mcp.tool()
async def wiki_index(
    knowledge_base_id: str,
    field: str = "source_time",
    from_time: str | None = None,
    to_time: str | None = None,
    include_unknown: bool = False,
) -> list[dict[str, Any]]:
    """读取已发布 Wiki 目录。"""
    async with tool_session("wiki:read", "wiki_index") as (session, user, _):
        space = await _wiki_space(session, user, knowledge_base_id)
        time_clause = _wiki_page_time_clause(field, from_time, to_time, include_unknown)
        pages = (
            await session.scalars(
                select(WikiPage).where(
                    WikiPage.space_id == space.id,
                    WikiPage.current_version_id.is_not(None),
                    time_clause,
                )
            )
        ).all()
        return [_wiki_page(item) for item in pages]


@mcp.tool()
async def wiki_search(
    knowledge_base_id: str,
    query: str,
    field: str = "source_time",
    from_time: str | None = None,
    to_time: str | None = None,
    include_unknown: bool = False,
) -> list[dict[str, Any]]:
    """搜索已发布 Wiki。"""
    async with tool_session("wiki:read", "wiki_search") as (session, user, _):
        space = await _wiki_space(session, user, knowledge_base_id)
        time_clause = _wiki_page_time_clause(field, from_time, to_time, include_unknown)
        pages = (
            await session.scalars(
                select(WikiPage)
                .where(
                    WikiPage.space_id == space.id,
                    WikiPage.current_version_id.is_not(None),
                    time_clause,
                    or_(
                        WikiPage.title.ilike(f"%{query}%"),
                        WikiPage.summary.ilike(f"%{query}%"),
                    ),
                )
                .limit(50)
            )
        ).all()
        return [_wiki_page(item) for item in pages]


@mcp.tool()
async def wiki_read(page_id: str) -> dict[str, Any]:
    """读取 Wiki 当前发布版本。"""
    async with tool_session("wiki:read", "wiki_read") as (session, user, _):
        page = await session.get(WikiPage, uuid.UUID(page_id))
        if page is None or page.current_version_id is None:
            raise ValueError("Wiki 页面不存在或未发布")
        space = await session.get(WikiSpace, page.space_id)
        if space is None:
            raise ValueError("Wiki 空间不存在")
        await require_knowledge_base_access(session, user, space.knowledge_base_id)
        version = await session.get(WikiPageVersion, page.current_version_id)
        sources = (
            (
                await session.scalars(
                    select(WikiPageSource)
                    .where(WikiPageSource.page_version_id == page.current_version_id)
                    .order_by(WikiPageSource.paragraph_key)
                )
            ).all()
            if version
            else []
        )
        return {
            **_wiki_page(page),
            "version_number": version.version_number if version else None,
            "content": version.content if version else "",
            "sources": [
                {
                    "document_id": str(source.document_id),
                    "chunk_id": str(source.chunk_id) if source.chunk_id else None,
                    "paragraph_key": source.paragraph_key,
                    "evidence_text": source.evidence_text,
                    "source_time": (source.source_time.isoformat() if source.source_time else None),
                }
                for source in sources
            ],
        }


def _wiki_page_time_clause(
    field: str,
    from_time: str | None,
    to_time: str | None,
    include_unknown: bool,
) -> ColumnElement[bool]:
    if field not in {"source_time", "created_at", "updated_at"}:
        raise ValueError("field 必须是 source_time、created_at 或 updated_at")
    if not from_time and not to_time:
        return true()
    column = getattr(WikiPage, field)
    conditions: list[ColumnElement[bool]] = [column.is_not(None)]
    if from_time:
        conditions.append(column >= _parse_aware_time(from_time))
    if to_time:
        conditions.append(column <= _parse_aware_time(to_time))
    known = and_(*conditions)
    return or_(known, column.is_(None)) if include_unknown else known


async def _graph_search(
    session: AsyncSession,
    space: WikiSpace,
    query: str,
    field: str,
    from_time: str | None,
    to_time: str | None,
    include_unknown: bool,
    limit: int,
) -> dict[str, Any]:
    clauses = [WikiNode.space_id == space.id, WikiNode.label.ilike(f"%{query}%")]
    node_time_clause = _wiki_graph_time_clause(
        WikiNode,
        field,
        from_time,
        to_time,
        include_unknown,
    )
    if node_time_clause is not None:
        clauses.append(node_time_clause)
    nodes = (await session.scalars(select(WikiNode).where(*clauses).limit(limit))).all()
    ids = [item.id for item in nodes]
    edge_clauses = [
        WikiEdge.space_id == space.id,
        or_(
            WikiEdge.source_node_id.in_(ids),
            WikiEdge.target_node_id.in_(ids),
        ),
    ]
    edge_time_clause = _wiki_graph_time_clause(
        WikiEdge,
        field,
        from_time,
        to_time,
        include_unknown,
    )
    if edge_time_clause is not None:
        edge_clauses.append(edge_time_clause)
    edges = (await session.scalars(select(WikiEdge).where(*edge_clauses).limit(200))).all()
    return {
        "nodes": [
            {
                "id": str(item.id),
                "type": item.node_type,
                "label": item.label,
                "source_time": item.source_time.isoformat() if item.source_time else None,
                "source_document_id": (
                    str(item.source_document_id) if item.source_document_id else None
                ),
                "source_page_id": str(item.source_page_id) if item.source_page_id else None,
            }
            for item in nodes
        ],
        "edges": [
            {
                "id": str(item.id),
                "source": str(item.source_node_id),
                "target": str(item.target_node_id),
                "type": item.edge_type,
                "evidence": item.evidence,
                "source_time": item.source_time.isoformat() if item.source_time else None,
                "source_document_id": (
                    str(item.source_document_id) if item.source_document_id else None
                ),
                "source_page_id": str(item.source_page_id) if item.source_page_id else None,
            }
            for item in edges
        ],
    }


def _wiki_graph_time_clause(
    model: type[WikiNode] | type[WikiEdge],
    field: str,
    from_time: str | None,
    to_time: str | None,
    include_unknown: bool,
) -> ColumnElement[bool] | None:
    if field not in {"source_time", "created_at", "updated_at"}:
        raise ValueError("field 必须是 source_time、created_at 或 updated_at")
    if not from_time and not to_time:
        return None
    column = getattr(model, field)
    conditions: list[ColumnElement[bool]] = [column.is_not(None)]
    if from_time:
        conditions.append(column >= _parse_aware_time(from_time))
    if to_time:
        conditions.append(column <= _parse_aware_time(to_time))
    known = and_(*conditions)
    return or_(known, column.is_(None)) if include_unknown else known


def _parse_aware_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError("时间必须包含时区")
    return parsed


@mcp.tool()
async def wiki_graph_search(
    knowledge_base_id: str,
    query: str,
    field: str = "source_time",
    from_time: str | None = None,
    to_time: str | None = None,
    include_unknown: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    """按文本和结构化时间范围搜索局部 Wiki 图。"""
    async with tool_session("wiki:read", "wiki_graph_search") as (session, user, _):
        space = await _wiki_space(session, user, knowledge_base_id)
        return await _graph_search(
            session,
            space,
            query,
            field,
            from_time,
            to_time,
            include_unknown,
            min(limit, 100),
        )


@mcp.tool()
async def wiki_graph_neighbors(
    knowledge_base_id: str,
    node_id: str,
    field: str = "source_time",
    from_time: str | None = None,
    to_time: str | None = None,
    include_unknown: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    """读取一个节点的局部邻居。"""
    async with tool_session("wiki:read", "wiki_graph_neighbors") as (session, user, _):
        space = await _wiki_space(session, user, knowledge_base_id)
        node = await session.scalar(
            select(WikiNode).where(
                WikiNode.id == uuid.UUID(node_id),
                WikiNode.space_id == space.id,
            )
        )
        if node is None:
            raise ValueError("图节点不存在")
        edge_conditions = [
            WikiEdge.space_id == space.id,
            or_(
                WikiEdge.source_node_id == node.id,
                WikiEdge.target_node_id == node.id,
            ),
        ]
        edge_time_clause = _wiki_graph_time_clause(
            WikiEdge,
            field,
            from_time,
            to_time,
            include_unknown,
        )
        if edge_time_clause is not None:
            edge_conditions.append(edge_time_clause)
        edges = (
            await session.scalars(select(WikiEdge).where(*edge_conditions).limit(min(limit, 500)))
        ).all()
        ids = {value for edge in edges for value in (edge.source_node_id, edge.target_node_id)}
        node_conditions: list[ColumnElement[bool]] = [WikiNode.id.in_(ids)]
        node_time_clause = _wiki_graph_time_clause(
            WikiNode,
            field,
            from_time,
            to_time,
            include_unknown,
        )
        if node_time_clause is not None:
            node_conditions.append(node_time_clause)
        nodes = (await session.scalars(select(WikiNode).where(*node_conditions))).all()
        return {
            "nodes": [
                {
                    "id": str(item.id),
                    "type": item.node_type,
                    "label": item.label,
                    "source_time": item.source_time.isoformat() if item.source_time else None,
                    "source_document_id": (
                        str(item.source_document_id) if item.source_document_id else None
                    ),
                    "source_page_id": str(item.source_page_id) if item.source_page_id else None,
                }
                for item in nodes
            ],
            "edges": [
                {
                    "id": str(item.id),
                    "source": str(item.source_node_id),
                    "target": str(item.target_node_id),
                    "type": item.edge_type,
                    "evidence": item.evidence,
                    "source_time": item.source_time.isoformat() if item.source_time else None,
                    "source_document_id": (
                        str(item.source_document_id) if item.source_document_id else None
                    ),
                    "source_page_id": str(item.source_page_id) if item.source_page_id else None,
                }
                for item in edges
            ],
        }


@mcp.tool()
async def wiki_timeline(
    knowledge_base_id: str,
    from_time: str,
    to_time: str,
    field: str = "source_time",
    include_unknown: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    """按结构化时间范围返回一个时期内的 Wiki 图内容。"""
    async with tool_session("wiki:read", "wiki_timeline") as (session, user, _):
        space = await _wiki_space(session, user, knowledge_base_id)
        return await _graph_search(
            session,
            space,
            "",
            field,
            from_time,
            to_time,
            include_unknown,
            min(limit, 500),
        )
