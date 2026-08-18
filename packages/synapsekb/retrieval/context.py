from __future__ import annotations

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from synapsekb.api.schemas import CitationRead
from synapsekb.database.models import Chunk


async def build_citation_context(
    session: AsyncSession,
    citations: list[CitationRead],
    *,
    neighbor_radius: int = 1,
    max_chars_per_citation: int = 6_000,
    max_total_chars: int = 60_000,
) -> str:
    """Expand matched chunks with a small adjacent window for answer synthesis.

    Search APIs still return only the exact matched chunks. RAG synthesis gets
    local continuity around each hit without sending whole documents, which is
    both cheaper and less likely to bury the relevant evidence in long reports.
    """

    if not citations:
        return ""
    matched_rows = list(
        (
            await session.scalars(
                select(Chunk).where(Chunk.id.in_([item.chunk_id for item in citations]))
            )
        ).all()
    )
    matched_by_id = {item.id: item for item in matched_rows}
    clauses = []
    for chunk in matched_rows:
        clauses.append(
            and_(
                Chunk.document_id == chunk.document_id,
                Chunk.status == "active",
                Chunk.ordinal.between(
                    max(0, chunk.ordinal - neighbor_radius),
                    chunk.ordinal + neighbor_radius,
                ),
            )
        )
    neighbor_rows = (
        list((await session.scalars(select(Chunk).where(or_(*clauses)))).all())
        if clauses
        else []
    )
    by_document: dict[object, list[Chunk]] = {}
    for chunk in neighbor_rows:
        by_document.setdefault(chunk.document_id, []).append(chunk)
    for chunks in by_document.values():
        chunks.sort(key=lambda item: item.ordinal)

    sections: list[str] = []
    used_chars = 0
    for citation in citations:
        matched = matched_by_id.get(citation.chunk_id)
        local_chunks = by_document.get(citation.document_id, [])
        parts = []
        for chunk in local_chunks:
            label = "命中片段" if chunk.id == citation.chunk_id else "相邻上下文"
            parts.append(f"【{label}·Chunk {chunk.ordinal}】\n{chunk.content.strip()}")
        expanded = "\n\n".join(parts).strip()
        if not expanded:
            expanded = citation.original_text
        expanded = expanded[:max_chars_per_citation]
        section = (
            f"[{citation.citation_number}] 知识库：{citation.knowledge_base_name}\n"
            f"文档：{citation.document_name}\n"
            f"来源时间：{citation.source_time or '未知'}\n"
            f"章节：{citation.section or (matched.section if matched else '未标注')}\n"
            f"{expanded}"
        )
        remaining = max_total_chars - used_chars
        if remaining <= 0:
            break
        sections.append(section[:remaining])
        used_chars += min(len(section), remaining)
    return "\n\n".join(sections)
