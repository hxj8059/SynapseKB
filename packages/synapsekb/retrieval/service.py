from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, Select, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from synapsekb.api.schemas import CitationRead, SearchRequest
from synapsekb.database.models import Chunk, Document
from synapsekb.document_processing.keyword import tokenize_for_postgres
from synapsekb.retrieval.filters import chunk_time_clause


@dataclass(slots=True)
class HybridRetriever:
    vector_candidates: int = 100
    keyword_candidates: int = 100
    rrf_k: int = 60

    def _base_filters(self, request: SearchRequest) -> list[ColumnElement[bool]]:
        clauses: list[ColumnElement[bool]] = [
            Chunk.status == "active",
            Chunk.knowledge_base_id.in_(request.knowledge_base_ids),
            chunk_time_clause(request.time_filter),
        ]
        if request.document_ids:
            clauses.append(Chunk.document_id.in_(request.document_ids))
        if request.tag_ids:
            from synapsekb.database.models import document_tag_links

            clauses.append(
                select(literal(1))
                .select_from(document_tag_links)
                .where(
                    document_tag_links.c.document_id == Chunk.document_id,
                    document_tag_links.c.tag_id.in_(request.tag_ids),
                )
                .exists()
            )
        return clauses

    def build_query(
        self,
        request: SearchRequest,
        query_vector: list[float] | None,
    ) -> Select[tuple[Chunk, Document, Any]]:
        filters = self._base_filters(request)
        keyword_query = func.plainto_tsquery("simple", tokenize_for_postgres(request.query))
        keyword = (
            select(
                Chunk.id.label("chunk_id"),
                func.row_number()
                .over(order_by=func.ts_rank_cd(Chunk.search_vector, keyword_query).desc())
                .label("rank"),
            )
            .where(*filters, Chunk.search_vector.op("@@")(keyword_query))
            .order_by(func.ts_rank_cd(Chunk.search_vector, keyword_query).desc())
            .limit(self.keyword_candidates)
            .cte("keyword")
        )

        if query_vector is not None:
            distance = Chunk.embedding.cosine_distance(query_vector)
            vector = (
                select(
                    Chunk.id.label("chunk_id"),
                    func.row_number().over(order_by=distance).label("rank"),
                )
                .where(*filters)
                .order_by(distance)
                .limit(self.vector_candidates)
                .cte("vector")
            )
            candidates = (
                select(keyword.c.chunk_id).union(select(vector.c.chunk_id)).cte("candidates")
            )
            score = func.coalesce(1.0 / (self.rrf_k + keyword.c.rank), 0.0) + func.coalesce(
                1.0 / (self.rrf_k + vector.c.rank), 0.0
            )
            statement = (
                select(Chunk, Document, score.label("score"))
                .join(Document, Document.id == Chunk.document_id)
                .join(candidates, candidates.c.chunk_id == Chunk.id)
                .outerjoin(keyword, keyword.c.chunk_id == Chunk.id)
                .outerjoin(vector, vector.c.chunk_id == Chunk.id)
                .order_by(score.desc())
                .limit(request.top_k)
            )
        else:
            score = 1.0 / (self.rrf_k + keyword.c.rank)
            statement = (
                select(Chunk, Document, score.label("score"))
                .join(Document, Document.id == Chunk.document_id)
                .join(keyword, keyword.c.chunk_id == Chunk.id)
                .order_by(score.desc())
                .limit(request.top_k)
            )
        return statement

    async def search(
        self,
        session: AsyncSession,
        request: SearchRequest,
        *,
        query_vector: list[float] | None,
    ) -> list[CitationRead]:
        rows = (await session.execute(self.build_query(request, query_vector))).all()
        return [
            CitationRead(
                citation_number=index,
                chunk_id=chunk.id,
                document_id=document.id,
                document_name=document.title,
                page_from=chunk.page_from,
                page_to=chunk.page_to,
                section=chunk.section,
                original_text=chunk.content,
                source_time=chunk.source_time,
                score=float(score),
            )
            for index, (chunk, document, score) in enumerate(rows, start=1)
        ]
