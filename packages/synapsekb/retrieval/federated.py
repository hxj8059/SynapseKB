from __future__ import annotations

from collections import defaultdict

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from synapsekb.api.schemas import CitationRead, SearchRequest
from synapsekb.database.models import KnowledgeBase, ProviderModel
from synapsekb.models.provider import create_provider
from synapsekb.retrieval.rerank import rerank_or_trim
from synapsekb.retrieval.service import HybridRetriever

logger = structlog.get_logger()


async def federated_search(
    session: AsyncSession,
    request: SearchRequest,
    knowledge_bases: list[KnowledgeBase],
    *,
    retriever: HybridRetriever | None = None,
) -> list[CitationRead]:
    """Search KBs with independent embedding configurations and merge results.

    A query vector is meaningful only for the model/dimension that produced it.
    Each compatible KB group therefore receives its own embedding call and SQL
    vector search. RRF scores share the same formula and are merged globally.
    A reranker is applied globally only when every selected KB chose the same
    rerank model; scores from different rerank providers are not comparable.
    """

    if not knowledge_bases:
        return []
    retriever = retriever or HybridRetriever()
    groups: dict[tuple[object, int], list[KnowledgeBase]] = defaultdict(list)
    for knowledge_base in knowledge_bases:
        groups[
            (knowledge_base.embedding_model_id, knowledge_base.embedding_dimensions)
        ].append(knowledge_base)

    candidates: list[CitationRead] = []
    for (model_id, dimensions), grouped_kbs in groups.items():
        query_vector: list[float] | None = None
        if model_id is not None:
            model = await session.get(ProviderModel, model_id)
            if model is None or model.kind != "embedding" or not model.is_enabled:
                raise ValueError("知识库配置的 Embedding 模型不可用")
            provider = create_provider(model, embedding_dimensions=dimensions)
            try:
                query_vector = (await provider.embeddings([request.query]))[0]
            finally:
                await provider.close()
        group_request = request.model_copy(
            update={
                "knowledge_base_ids": [item.id for item in grouped_kbs],
                "top_k": min(request.top_k * 3, 100),
            }
        )
        candidates.extend(
            await retriever.search(
                session,
                group_request,
                query_vector=query_vector,
                embedding_dimensions=dimensions,
            )
        )

    deduplicated = list({item.chunk_id: item for item in candidates}.values())
    deduplicated.sort(key=lambda item: item.score, reverse=True)
    rerank_ids = {item.rerank_model_id for item in knowledge_bases}
    if len(rerank_ids) == 1:
        return await rerank_or_trim(
            session,
            request.query,
            deduplicated,
            request.top_k,
            model_id=next(iter(rerank_ids)),
            allow_default_model=False,
        )

    logger.info(
        "federated_rerank_skipped",
        knowledge_base_count=len(knowledge_bases),
        reason="different_rerank_models",
    )
    selected = deduplicated[: request.top_k]
    for index, citation in enumerate(selected, 1):
        citation.citation_number = index
    return selected
