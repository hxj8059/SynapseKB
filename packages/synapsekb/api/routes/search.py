from __future__ import annotations

from fastapi import APIRouter, HTTPException

from synapsekb.api.schemas import SearchRequest, SearchResponse
from synapsekb.auth.dependencies import CurrentUser, DatabaseSession
from synapsekb.auth.policy import require_knowledge_base_access
from synapsekb.config import get_settings
from synapsekb.database.models import KnowledgeBase
from synapsekb.retrieval.federated import federated_search
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
    settings = get_settings()
    retriever = HybridRetriever(
        vector_candidates=settings.retrieval_vector_candidates,
        keyword_candidates=settings.retrieval_keyword_candidates,
        rrf_k=settings.retrieval_rrf_k,
    )
    try:
        results = await federated_search(
            session,
            payload,
            knowledge_bases,
            retriever=retriever,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SearchResponse(
        query=payload.query,
        time_filter=payload.time_filter,
        results=results,
    )
