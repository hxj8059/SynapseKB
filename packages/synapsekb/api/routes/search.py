from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from synapsekb.api.schemas import SearchRequest, SearchResponse
from synapsekb.auth.dependencies import CurrentUser, DatabaseSession
from synapsekb.auth.policy import require_knowledge_base_access
from synapsekb.config import get_settings
from synapsekb.database.models import KnowledgeBase, ProviderModel
from synapsekb.models.provider import create_provider
from synapsekb.retrieval.rerank import rerank_or_trim
from synapsekb.retrieval.service import HybridRetriever

router = APIRouter()


@router.post("", response_model=SearchResponse)
async def knowledge_search(
    payload: SearchRequest,
    user: CurrentUser,
    session: DatabaseSession,
) -> SearchResponse:
    knowledge_bases: list[KnowledgeBase] = []
    for knowledge_base_id in set(payload.knowledge_base_ids):
        knowledge_bases.append(
            await require_knowledge_base_access(session, user, knowledge_base_id)
        )
    embedding_configs = {
        (item.embedding_model_id, item.embedding_dimensions) for item in knowledge_bases
    }
    if len(embedding_configs) > 1:
        raise HTTPException(
            status_code=409,
            detail="所选知识库使用不同 Embedding 模型或维度，不能在同一次向量检索中混用",
        )
    model_id, embedding_dimensions = next(iter(embedding_configs), (None, None))
    query_vector: list[float] | None = None
    if model_id is not None:
        model = await session.scalar(
            select(ProviderModel).where(
                ProviderModel.id == model_id,
                ProviderModel.kind == "embedding",
                ProviderModel.is_enabled.is_(True),
            )
        )
        if model is None:
            raise HTTPException(status_code=409, detail="Embedding 模型不可用")
        provider = create_provider(model, embedding_dimensions=embedding_dimensions)
        try:
            query_vector = (await provider.embeddings([payload.query]))[0]
        finally:
            await provider.close()
    settings = get_settings()
    retriever = HybridRetriever(
        vector_candidates=settings.retrieval_vector_candidates,
        keyword_candidates=settings.retrieval_keyword_candidates,
        rrf_k=settings.retrieval_rrf_k,
    )
    candidate_request = payload.model_copy(update={"top_k": min(payload.top_k * 3, 100)})
    candidates = await retriever.search(
        session,
        candidate_request,
        query_vector=query_vector,
        embedding_dimensions=embedding_dimensions,
    )
    rerank_model_ids = {item.rerank_model_id for item in knowledge_bases}
    if len(rerank_model_ids) > 1:
        raise HTTPException(status_code=409, detail="所选知识库使用不同 Rerank 模型")
    results = await rerank_or_trim(
        session,
        payload.query,
        candidates,
        payload.top_k,
        model_id=next(iter(rerank_model_ids), None),
        allow_default_model=False,
    )
    return SearchResponse(
        query=payload.query,
        time_filter=payload.time_filter,
        results=results,
    )
