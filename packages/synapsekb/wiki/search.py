from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime

import structlog
from pgvector.sqlalchemy import Vector
from sqlalchemy import ColumnElement, case, cast, exists, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from synapsekb.database.models import (
    KnowledgeBase,
    ProviderModel,
    WikiNode,
    WikiNodeAlias,
    WikiPage,
    WikiSpace,
)
from synapsekb.models.provider import create_provider
from synapsekb.wiki.entity_resolution import normalize_wiki_label

logger = structlog.get_logger()

_MAX_QUERY_LENGTH = 500
_MAX_LIMIT = 20
_MIN_CANDIDATES = 40
_MAX_CANDIDATES = 100
_QUERY_EMBEDDING_TIMEOUT_SECONDS = 20


@dataclass(frozen=True, slots=True)
class WikiSearchItem:
    page_id: uuid.UUID
    node_id: uuid.UUID
    title: str
    summary: str
    node_type: str
    source_time: datetime | None
    relevance_score: float
    semantic_score: float | None
    keyword_score: float | None
    matched_by: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WikiSearchResult:
    items: tuple[WikiSearchItem, ...]
    retrieval_mode: str
    embedding_error: str | None
    semantic_candidate_count: int
    keyword_candidate_count: int


@dataclass(slots=True)
class _Candidate:
    page: WikiPage
    node: WikiNode
    semantic_score: float | None = None
    semantic_rank: int | None = None
    keyword_score: float | None = None
    keyword_rank: int | None = None
    keyword_match: str | None = None


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _bounded_score(value: float) -> float:
    return max(0.0, min(1.0, value))


def _combined_score(candidate: _Candidate) -> float:
    scores = [
        score
        for score in (candidate.semantic_score, candidate.keyword_score)
        if score is not None
    ]
    if not scores:
        return 0.0
    if candidate.semantic_score is not None and candidate.keyword_score is not None:
        base = 0.7 * candidate.semantic_score + 0.3 * candidate.keyword_score
    else:
        base = scores[0]

    ranks = [
        rank
        for rank in (candidate.semantic_rank, candidate.keyword_rank)
        if rank is not None
    ]
    rank_score = sum(61 / (60 + rank) for rank in ranks) / len(ranks)
    combined = 0.95 * base + 0.05 * rank_score
    if candidate.keyword_match in {"title_exact", "alias_exact"}:
        combined = max(combined, candidate.keyword_score or 0.0)
    return round(_bounded_score(combined), 6)


async def _keyword_candidates(
    session: AsyncSession,
    *,
    space: WikiSpace,
    query: str,
    time_clause: ColumnElement[bool],
    node_type: str | None,
    candidate_limit: int,
) -> list[tuple[WikiPage, WikiNode, float, str]]:
    normalized_query = normalize_wiki_label(query)
    alias_exact = (
        exists(
            select(WikiNodeAlias.id).where(
                WikiNodeAlias.node_id == WikiNode.id,
                WikiNodeAlias.normalized_alias == normalized_query,
            )
        )
        if normalized_query
        else false()
    )
    pattern = f"%{_escape_like(query)}%"
    title_exact = func.lower(func.trim(WikiPage.title)) == query.casefold()
    title_contains = WikiPage.title.ilike(pattern, escape="\\")
    summary_contains = WikiPage.summary.ilike(pattern, escape="\\")
    title_similarity = func.similarity(WikiPage.title, query)
    keyword_score = case(
        (title_exact, 1.0),
        (alias_exact, 0.99),
        (title_contains, 0.88),
        (summary_contains, 0.65),
        else_=title_similarity,
    )
    keyword_match = case(
        (title_exact, "title_exact"),
        (alias_exact, "alias_exact"),
        (title_contains, "title"),
        (summary_contains, "summary"),
        else_="title_fuzzy",
    )
    conditions: list[ColumnElement[bool]] = [
        WikiPage.space_id == space.id,
        WikiPage.current_version_id.is_not(None),
        WikiPage.is_archived.is_(False),
        WikiNode.space_id == space.id,
        WikiNode.page_id.is_not(None),
        time_clause,
        or_(title_contains, summary_contains, alias_exact, title_similarity >= 0.2),
    ]
    if node_type is not None:
        conditions.append(WikiNode.node_type == node_type)
    rows = (
        await session.execute(
            select(
                WikiPage,
                WikiNode,
                keyword_score.label("keyword_score"),
                keyword_match.label("keyword_match"),
            )
            .join(WikiNode, WikiNode.page_id == WikiPage.id)
            .where(*conditions)
            .order_by(keyword_score.desc(), WikiPage.title, WikiPage.id)
            .limit(candidate_limit)
        )
    ).all()
    return [
        (page, node, _bounded_score(float(score)), str(match))
        for page, node, score, match in rows
    ]


async def _semantic_candidates(
    session: AsyncSession,
    *,
    knowledge_base: KnowledgeBase,
    space: WikiSpace,
    query: str,
    time_clause: ColumnElement[bool],
    node_type: str | None,
    candidate_limit: int,
) -> tuple[list[tuple[WikiPage, WikiNode, float]], str | None]:
    if knowledge_base.embedding_model_id is None:
        return [], "知识库未配置 Embedding 模型"
    model = await session.get(ProviderModel, knowledge_base.embedding_model_id)
    if model is None or model.kind != "embedding" or not model.is_enabled:
        return [], "知识库 Embedding 模型不存在或已停用"

    provider = create_provider(
        model,
        embedding_dimensions=knowledge_base.embedding_dimensions,
    )
    try:
        timeout = min(
            max(model.timeout_seconds, 1),
            _QUERY_EMBEDDING_TIMEOUT_SECONDS,
        )
        async with asyncio.timeout(timeout):
            vectors = await provider.embeddings([query])
    except Exception as exc:
        logger.warning(
            "wiki_search_embedding_failed",
            knowledge_base_id=str(knowledge_base.id),
            error_type=type(exc).__name__,
        )
        return [], f"{type(exc).__name__}: {exc}"[:500]
    finally:
        await provider.close()
    if len(vectors) != 1 or len(vectors[0]) != knowledge_base.embedding_dimensions:
        return [], (
            "Embedding API 返回维度与知识库锁定的 "
            f"{knowledge_base.embedding_dimensions} 维不一致"
        )

    distance = cast(
        WikiNode.embedding,
        Vector(knowledge_base.embedding_dimensions),
    ).cosine_distance(vectors[0])
    conditions: list[ColumnElement[bool]] = [
        WikiPage.space_id == space.id,
        WikiPage.current_version_id.is_not(None),
        WikiPage.is_archived.is_(False),
        WikiNode.space_id == space.id,
        WikiNode.page_id.is_not(None),
        WikiNode.embedding.is_not(None),
        WikiNode.embedding_model_id == model.id,
        func.vector_dims(WikiNode.embedding) == knowledge_base.embedding_dimensions,
        time_clause,
    ]
    if node_type is not None:
        conditions.append(WikiNode.node_type == node_type)
    rows = (
        await session.execute(
            select(WikiPage, WikiNode, distance.label("distance"))
            .join(WikiNode, WikiNode.page_id == WikiPage.id)
            .where(*conditions)
            .order_by(distance, WikiPage.id)
            .limit(candidate_limit)
        )
    ).all()
    return [
        (page, node, _bounded_score(1 - float(raw_distance)))
        for page, node, raw_distance in rows
        if raw_distance is not None
    ], None


async def hybrid_wiki_search(
    session: AsyncSession,
    *,
    knowledge_base: KnowledgeBase,
    space: WikiSpace,
    query: str,
    time_clause: ColumnElement[bool],
    limit: int = 10,
    node_type: str | None = None,
) -> WikiSearchResult:
    """Search published Wiki page nodes with vector recall and keyword fallback.

    Page vectors are generated from ``title + summary[:800]`` by
    :func:`ensure_page_node_embeddings`. Scores only rank candidates; callers
    must still inspect the selected pages and evidence before making claims.
    """

    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("query 不能为空")
    if len(normalized_query) > _MAX_QUERY_LENGTH:
        raise ValueError(f"query 最长 {_MAX_QUERY_LENGTH} 个字符")
    bounded_limit = min(max(limit, 1), _MAX_LIMIT)
    candidate_limit = min(max(bounded_limit * 4, _MIN_CANDIDATES), _MAX_CANDIDATES)

    keyword_rows = await _keyword_candidates(
        session,
        space=space,
        query=normalized_query,
        time_clause=time_clause,
        node_type=node_type,
        candidate_limit=candidate_limit,
    )
    semantic_rows, embedding_error = await _semantic_candidates(
        session,
        knowledge_base=knowledge_base,
        space=space,
        query=normalized_query,
        time_clause=time_clause,
        node_type=node_type,
        candidate_limit=candidate_limit,
    )

    candidates: dict[uuid.UUID, _Candidate] = {}
    for rank, (page, node, score, match) in enumerate(keyword_rows, 1):
        candidate = candidates.setdefault(page.id, _Candidate(page=page, node=node))
        if candidate.keyword_score is None or score > candidate.keyword_score:
            candidate.keyword_score = score
            candidate.keyword_rank = rank
            candidate.keyword_match = match
    for rank, (page, node, score) in enumerate(semantic_rows, 1):
        candidate = candidates.setdefault(page.id, _Candidate(page=page, node=node))
        if candidate.semantic_score is None or score > candidate.semantic_score:
            candidate.semantic_score = score
            candidate.semantic_rank = rank

    ranked = sorted(
        candidates.values(),
        key=lambda item: (-_combined_score(item), item.page.title, str(item.page.id)),
    )[:bounded_limit]
    items = tuple(
        WikiSearchItem(
            page_id=candidate.page.id,
            node_id=candidate.node.id,
            title=candidate.page.title,
            summary=candidate.page.summary,
            node_type=candidate.node.node_type,
            source_time=candidate.page.source_time,
            relevance_score=_combined_score(candidate),
            semantic_score=(
                round(candidate.semantic_score, 6)
                if candidate.semantic_score is not None
                else None
            ),
            keyword_score=(
                round(candidate.keyword_score, 6)
                if candidate.keyword_score is not None
                else None
            ),
            matched_by=tuple(
                method
                for method, present in (
                    (candidate.keyword_match or "keyword", candidate.keyword_score is not None),
                    ("vector", candidate.semantic_score is not None),
                )
                if present
            ),
        )
        for candidate in ranked
    )
    if semantic_rows:
        retrieval_mode = "hybrid"
    else:
        retrieval_mode = "keyword_fallback"
        if embedding_error is None:
            embedding_error = "已发布 Wiki 节点向量尚未就绪"
    return WikiSearchResult(
        items=items,
        retrieval_mode=retrieval_mode,
        embedding_error=embedding_error,
        semantic_candidate_count=len(semantic_rows),
        keyword_candidate_count=len(keyword_rows),
    )
