from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from synapsekb.api.schemas import RagRequest, SearchRequest, TimeFilter
from synapsekb.auth.dependencies import CurrentUser, DatabaseSession
from synapsekb.auth.policy import require_knowledge_base_access
from synapsekb.config import get_settings
from synapsekb.database.models import (
    ChatMessage,
    ChatSession,
    KnowledgeBase,
    MessageCitation,
    ProviderModel,
)
from synapsekb.database.session import AsyncSessionFactory
from synapsekb.models.provider import DeterministicMockProvider, create_provider
from synapsekb.retrieval.rerank import rerank_or_trim
from synapsekb.retrieval.service import HybridRetriever
from synapsekb.temporal.parser import resolve_time_ranges

router = APIRouter()


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


async def _resolve_models(
    knowledge_bases: list[KnowledgeBase],
    chat_model_id: uuid.UUID | None,
    session: DatabaseSession,
) -> tuple[ProviderModel | None, int | None, ProviderModel, uuid.UUID | None, int]:
    embedding_configs = {
        (item.embedding_model_id, item.embedding_dimensions) for item in knowledge_bases
    }
    if len(embedding_configs) > 1:
        raise HTTPException(status_code=409, detail="所选知识库的 Embedding 模型或维度不一致")
    embedding_model = None
    embedding_id, embedding_dimensions = next(iter(embedding_configs), (None, None))
    if embedding_id:
        embedding_model = await session.get(ProviderModel, embedding_id)
    configured_chat_ids = {item.rag_chat_model_id for item in knowledge_bases}
    if chat_model_id:
        chat_model = await session.get(ProviderModel, chat_model_id)
        if chat_model is None or chat_model.kind != "chat" or not chat_model.is_enabled:
            raise HTTPException(status_code=422, detail="指定的 RAG Chat 模型不存在或不可用")
    else:
        if len(configured_chat_ids) > 1:
            raise HTTPException(status_code=409, detail="所选知识库的 RAG Chat 模型不一致")
        configured_chat_id = next(iter(configured_chat_ids), None)
        chat_model = (
            await session.get(ProviderModel, configured_chat_id)
            if configured_chat_id
            else None
        )
        if chat_model is None:
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
                raise HTTPException(
                    status_code=409,
                    detail="存在多个 Chat 模型，请在知识库设置中指定 RAG Chat 模型",
                )
            chat_model = available[0] if available else None
    if chat_model is None:
        raise HTTPException(status_code=409, detail="尚未配置可用 Chat 模型")
    rerank_ids = {item.rerank_model_id for item in knowledge_bases}
    if len(rerank_ids) > 1:
        raise HTTPException(status_code=409, detail="所选知识库的 Rerank 模型不一致")
    rerank_model_id = next(iter(rerank_ids), None)
    max_output_tokens = min(item.rag_max_output_tokens for item in knowledge_bases)
    return embedding_model, embedding_dimensions, chat_model, rerank_model_id, max_output_tokens


async def _stream_answer(
    *,
    payload: RagRequest,
    session_id: uuid.UUID,
    embedding_model_id: uuid.UUID | None,
    embedding_dimensions: int | None,
    chat_model_id: uuid.UUID,
    rerank_model_id: uuid.UUID | None,
    max_output_tokens: int,
    filters: list[TimeFilter | None],
) -> AsyncIterator[str]:
    settings = get_settings()
    async with AsyncSessionFactory() as session:
        embedding_model = (
            await session.get(ProviderModel, embedding_model_id) if embedding_model_id else None
        )
        query_vector = None
        if embedding_model:
            embedding_provider = create_provider(
                embedding_model,
                embedding_dimensions=embedding_dimensions,
            )
            try:
                query_vector = (await embedding_provider.embeddings([payload.query]))[0]
            finally:
                await embedding_provider.close()
        retriever = HybridRetriever(
            settings.retrieval_vector_candidates,
            settings.retrieval_keyword_candidates,
            settings.retrieval_rrf_k,
        )
        citations = []
        for time_filter in filters:
            request = SearchRequest(
                query=payload.query,
                knowledge_base_ids=payload.knowledge_base_ids,
                document_ids=payload.document_ids,
                tag_ids=payload.tag_ids,
                time_filter=time_filter,
                top_k=min(payload.top_k * 3, 100),
            )
            period_candidates = await retriever.search(
                session,
                request,
                query_vector=query_vector,
                embedding_dimensions=embedding_dimensions,
            )
            citations.extend(
                await rerank_or_trim(
                    session,
                    payload.query,
                    period_candidates,
                    payload.top_k,
                    model_id=rerank_model_id,
                    allow_default_model=False,
                )
            )
        deduplicated = list({citation.chunk_id: citation for citation in citations}.values())
        for index, citation in enumerate(deduplicated, start=1):
            citation.citation_number = index
            yield _sse("citation", citation.model_dump(mode="json"))
        yield _sse(
            "retrieval.summary",
            {
                "result_count": len(deduplicated),
                "time_filters": [
                    item.model_dump(mode="json", by_alias=True) if item else None
                    for item in filters
                ],
            },
        )

        context = "\n\n".join(
            f"[{item.citation_number}] 文档：{item.document_name}\n"
            f"来源时间：{item.source_time or '未知'}\n"
            f"章节：{item.section or '未标注'}\n"
            f"内容：{item.original_text}"
            for item in deduplicated
        )[:60_000]
        chat_model = await session.get(ProviderModel, chat_model_id)
        if chat_model is None:
            yield _sse("error", {"message": "Chat 模型已被删除"})
            return
        provider = create_provider(chat_model)
        if isinstance(provider, DeterministicMockProvider):
            await provider.close()
            yield _sse("error", {"message": "Mock Provider 不支持 Chat"})
            return
        history = list(
            (
                await session.scalars(
                    select(ChatMessage)
                    .where(ChatMessage.session_id == session_id)
                    .order_by(ChatMessage.created_at.desc())
                    .limit(20)
                )
            ).all()
        )
        history_messages = [
            {"role": item.role, "content": item.content} for item in reversed(history)
        ]
        assistant_text = ""
        started_at = time.perf_counter()
        try:
            async for delta in provider.chat_stream(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是 SynapseKB 问答助手。只能依据给定知识片段回答；"
                            "关键结论必须使用 [编号] 引用。资料不足时明确说明，不得编造。"
                        ),
                    },
                    *history_messages,
                    {
                        "role": "user",
                        "content": f"问题：{payload.query}\n\n知识片段：\n{context}",
                    },
                ],
                max_tokens=max_output_tokens,
            ):
                assistant_text += delta
                yield _sse("assistant.delta", {"delta": delta})
            finish_reason = provider.last_chat_finish_reason
            usage = dict(provider.last_chat_usage)
        except asyncio.CancelledError:
            raise
        finally:
            await provider.close()
        if finish_reason == "length":
            yield _sse(
                "error",
                {
                    "message": (
                        "回答达到输出上限，未保存为完整回答。请在知识库模型设置中"
                        f"提高 RAG 输出上限（当前 {max_output_tokens} Token）后重试。"
                    ),
                    "finish_reason": finish_reason,
                },
            )
            return

        user_message = ChatMessage(
            session_id=session_id,
            role="user",
            content=payload.query,
            retrieval_params={
                "knowledge_base_ids": [str(item) for item in payload.knowledge_base_ids],
                "time_filters": [
                    item.model_dump(mode="json", by_alias=True) if item else None
                    for item in filters
                ],
            },
        )
        session.add(user_message)
        assistant_message = ChatMessage(
            session_id=session_id,
            role="assistant",
            content=assistant_text,
            model_id=chat_model.id,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            latency_ms=round((time.perf_counter() - started_at) * 1000),
        )
        session.add(assistant_message)
        await session.flush()
        for citation in deduplicated:
            session.add(
                MessageCitation(
                    message_id=assistant_message.id,
                    chunk_id=citation.chunk_id,
                    citation_number=citation.citation_number,
                    document_title=citation.document_name,
                    page_from=citation.page_from,
                    page_to=citation.page_to,
                    section=citation.section,
                    original_text=citation.original_text,
                    source_time=citation.source_time,
                )
            )
        chat_session = await session.get(ChatSession, session_id)
        if chat_session is not None:
            chat_session.updated_at = datetime.now(UTC)
        await session.commit()
        yield _sse(
            "completed",
            {
                "session_id": session_id,
                "message_id": assistant_message.id,
                "citation_count": len(deduplicated),
            },
        )


@router.post("/stream")
async def rag_stream(
    payload: RagRequest,
    user: CurrentUser,
    session: DatabaseSession,
) -> StreamingResponse:
    settings = get_settings()
    knowledge_bases = [
        await require_knowledge_base_access(session, user, item)
        for item in set(payload.knowledge_base_ids)
    ]
    (
        embedding_model,
        embedding_dimensions,
        chat_model,
        rerank_model_id,
        max_output_tokens,
    ) = await _resolve_models(knowledge_bases, payload.chat_model_id, session)
    if payload.session_id:
        chat_session = await session.scalar(
            select(ChatSession).where(
                ChatSession.id == payload.session_id,
                ChatSession.user_id == user.id,
            )
        )
        if chat_session is None:
            raise HTTPException(status_code=404, detail="对话不存在")
    else:
        chat_session = ChatSession(user_id=user.id, title=payload.query[:80], mode="rag")
        session.add(chat_session)
        await session.commit()

    filters: list[TimeFilter | None]
    if payload.time_filter is not None:
        filters = [payload.time_filter]
    else:
        resolved = resolve_time_ranges(
            payload.query,
            timezone=user.timezone or settings.default_timezone,
        )
        filters = [
            TimeFilter(
                field="source_time",
                from_=item.from_time,
                to=item.to_time,
                include_unknown=False,
            )
            for item in resolved
        ] or [None]
    return StreamingResponse(
        _stream_answer(
            payload=payload,
            session_id=chat_session.id,
            embedding_model_id=embedding_model.id if embedding_model else None,
            embedding_dimensions=embedding_dimensions,
            chat_model_id=chat_model.id,
            rerank_model_id=rerank_model_id,
            max_output_tokens=max_output_tokens,
            filters=filters,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
