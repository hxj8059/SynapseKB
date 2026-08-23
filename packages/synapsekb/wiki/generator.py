from __future__ import annotations

import json
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from synapsekb.database.models import (
    Chunk,
    Document,
    KnowledgeBase,
    WikiEdge,
    WikiNode,
    WikiPage,
    WikiPageSource,
    WikiPageVersion,
    WikiSpace,
    WikiUpdateJob,
)
from synapsekb.database.session import AsyncSessionFactory
from synapsekb.models.provider import (
    DeterministicMockProvider,
    OpenAICompatibleProvider,
    create_provider,
)
from synapsekb.wiki.document_state import (
    job_expected_document_ids,
    mark_job_documents_failed,
    mark_job_documents_pending,
    mark_job_documents_running,
    mark_job_documents_succeeded,
)
from synapsekb.wiki.entity_resolution import (
    HistoricalWikiNode,
    WikiHistoryResolver,
    add_node_alias,
    canonicalize_wiki_entity_title,
    ensure_canonical_node_aliases,
    ensure_page_node_embeddings,
    resolve_exact_alias,
    wiki_label_aliases,
)
from synapsekb.wiki.model_selection import resolve_wiki_model
from synapsekb.wiki.publisher import publish_generation
from synapsekb.wiki.structured import (
    GeneratedWikiGraph,
    parse_generated_wiki_graph,
    wiki_generation_system_prompt,
)

logger = structlog.get_logger()

WIKI_GENERATION_MAX_TOKENS = 10_000
WIKI_COMPACT_RETRY_MAX_TOKENS = 10_000
WIKI_CHUNKS_PER_BATCH = 16
WIKI_RECOVERY_CHUNKS_PER_BATCH = 4


def _evenly_sample[T](items: Sequence[T], limit: int) -> list[T]:
    if len(items) <= limit:
        return list(items)
    if limit <= 1:
        return [items[0]]
    indexes = {round(index * (len(items) - 1) / (limit - 1)) for index in range(limit)}
    return [items[index] for index in sorted(indexes)]


def _complete_chunk_batches[T](
    items: Sequence[T],
    batch_size: int = WIKI_CHUNKS_PER_BATCH,
) -> list[list[T]]:
    """Partition every item exactly once instead of sampling the document."""

    if batch_size <= 0:
        raise ValueError("Wiki Chunk 批大小必须大于 0")
    return [list(items[start : start + batch_size]) for start in range(0, len(items), batch_size)]


def _node_slug(node_type: str, title: str) -> str:
    base = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff-]+", "-", title).strip("-")
    digest = sha256(f"{node_type}:{title}".casefold().encode()).hexdigest()[:10]
    return f"{base[:80] or 'node'}-{digest}".lower()


@dataclass(slots=True)
class _NodeAggregate:
    node_type: str
    title: str
    summary: str
    sections: list[tuple[str, str, datetime | None]] = field(default_factory=list)
    sources: dict[uuid.UUID, tuple[Document, Chunk]] = field(default_factory=dict)
    aliases: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class _RelationAggregate:
    source_slug: str
    target_slug: str
    relation_type: str
    evidence: str
    source_document_id: uuid.UUID
    source_time: datetime | None


async def _generate_document_graph(
    provider: OpenAICompatibleProvider,
    knowledge_base: KnowledgeBase,
    document: Document,
    chunks: list[Chunk],
    *,
    historical_nodes: list[HistoricalWikiNode] | None = None,
    compact: bool = False,
    batch_index: int = 1,
    batch_count: int = 1,
) -> GeneratedWikiGraph:
    historical_nodes = historical_nodes or []
    context = "\n\n".join(
        (
            f"[{index}] 页码 {chunk.page_from or '未知'}，"
            f"章节 {chunk.section or '未知'}：{chunk.content}"
        )
        for index, chunk in enumerate(chunks, 1)
    )
    historical_context = json.dumps(
        [item.prompt_payload() for item in historical_nodes],
        ensure_ascii=False,
    )
    response = await provider.chat_json(
        [
            {
                "role": "system",
                "content": wiki_generation_system_prompt(
                    node_types=knowledge_base.wiki_node_types,
                    custom_prompt=knowledge_base.wiki_generation_prompt,
                ),
            },
            {
                "role": "user",
                "content": (
                    f"文档标题：{document.title}\n"
                    f"文档 source_time：{document.source_time or '未知'}\n\n"
                    f"当前材料批次：{batch_index}/{batch_count}。"
                    "同一文档的所有批次都会分别分析，请只提炼当前批次有直接证据的内容。\n\n"
                    "相关历史 Wiki 节点候选（不是同一实体时必须忽略）：\n"
                    f"{historical_context}"
                    "\n\n"
                    + (
                        "这是截断后的紧凑重试：最多提取 3 个节点，"
                        "每个 Markdown 不超过 180 个中文字符，关系不超过 6 条。\n\n"
                        if compact
                        else ""
                    )
                    + f"材料：\n{context}"
                ),
            },
        ],
        max_tokens=(WIKI_COMPACT_RETRY_MAX_TOKENS if compact else WIKI_GENERATION_MAX_TOKENS),
        disable_reasoning=True,
    )
    return parse_generated_wiki_graph(
        response,
        allowed_node_types=knowledge_base.wiki_node_types,
        allowed_existing_pages={item.page_id: item.node_type for item in historical_nodes},
        forbidden_titles={document.title, document.filename},
    )


async def generate_wiki_job(job_id: uuid.UUID) -> None:
    async with AsyncSessionFactory() as session:
        selected_document_ids: list[uuid.UUID] = []
        job = await session.get(WikiUpdateJob, job_id)
        if job is None or job.status == "published":
            return
        space = await session.get(WikiSpace, job.space_id)
        if space is None:
            raise RuntimeError("Wiki 空间不存在")
        knowledge_base = await session.scalar(
            select(KnowledgeBase).where(KnowledgeBase.id == space.knowledge_base_id)
        )
        if knowledge_base is None:
            raise RuntimeError("知识库不存在")
        try:
            model = await resolve_wiki_model(session, knowledge_base, job)
            if job.model_id is None:
                job.model_id = model.id
            provider = create_provider(model)
            if isinstance(provider, DeterministicMockProvider):
                raise RuntimeError("Mock Provider 不支持 Wiki 生成")
        except Exception as exc:
            error_summary = f"{type(exc).__name__}: {exc}"[:1000]
            job.status = "failed"
            job.error_summary = error_summary
            await mark_job_documents_failed(
                session,
                job=job,
                document_ids=job_expected_document_ids(job),
                error_summary=error_summary,
            )
            await session.commit()
            raise
        initial_quality_report = dict(job.quality_report)
        recovery_count = int(initial_quality_report.get("recovery_count", 0) or 0)
        if job.status == "running":
            recovery_count += 1
        await session.execute(
            delete(WikiPageVersion).where(WikiPageVersion.generation_id == job.generation_id)
        )
        job.status = "running"
        job.candidate_version = (space.published_version or 0) + 1
        job.error_summary = None
        job.quality_report = {
            **initial_quality_report,
            "recovery_count": recovery_count,
        }
        await session.commit()
        history_resolver: WikiHistoryResolver | None = None
        try:
            document_query = (
                select(Document)
                .where(
                    Document.knowledge_base_id == knowledge_base.id,
                    Document.status == "ready",
                )
                .order_by(Document.created_at, Document.id)
            )
            if job.affected_document_ids:
                document_query = document_query.where(Document.id.in_(job.affected_document_ids))
            documents = list((await session.scalars(document_query)).all())
            if not documents:
                raise RuntimeError("没有可用于 Wiki 的文档")
            selected_document_ids = [document.id for document in documents]
            await mark_job_documents_running(session, job=job, documents=documents)
            await session.commit()
            existing_pages = list(
                (
                    await session.scalars(
                        select(WikiPage).where(
                            WikiPage.space_id == space.id,
                            WikiPage.current_version_id.is_not(None),
                            WikiPage.is_archived.is_(False),
                        )
                    )
                ).all()
            )
            existing_nodes = list(
                (
                    await session.scalars(
                        select(WikiNode).where(
                            WikiNode.space_id == space.id,
                            WikiNode.page_id.is_not(None),
                        )
                    )
                ).all()
            )
            existing_nodes_by_page = {
                node.page_id: node for node in existing_nodes if node.page_id is not None
            }
            await ensure_canonical_node_aliases(session, existing_nodes)
            _embedded_count, history_embedding_error = await ensure_page_node_embeddings(
                session,
                knowledge_base,
                existing_pages,
                existing_nodes_by_page,
            )
            await session.commit()
            history_resolver = await WikiHistoryResolver.create(
                session,
                knowledge_base,
                space.id,
            )
            aggregates: dict[str, _NodeAggregate] = {}
            relations: list[_RelationAggregate] = []
            recovered_batches: list[dict[str, object]] = []
            retried_documents: list[dict[str, object]] = []
            coverage_documents: list[dict[str, object]] = []
            historical_candidates_used = 0
            reused_history_pages: set[uuid.UUID] = set()
            expected_document_ids = [str(document.id) for document in documents]
            job.quality_report = {
                **job.quality_report,
                "document_coverage": {
                    "expected_document_count": len(documents),
                    "processed_document_count": 0,
                    "expected_document_ids": expected_document_ids,
                    "documents": [],
                },
            }
            job.change_summary = f"准备分析 {len(documents)} 份文档"
            await session.commit()
            for document_index, document in enumerate(documents, 1):
                await session.refresh(job)
                if job.cancel_requested_at is not None:
                    job.status = "cancelled"
                    await mark_job_documents_pending(session, job_id=job.id)
                    await session.commit()
                    return
                all_chunks = list(
                    (
                        await session.scalars(
                            select(Chunk)
                            .where(
                                Chunk.document_id == document.id,
                                Chunk.status == "active",
                            )
                            .order_by(Chunk.ordinal)
                        )
                    ).all()
                )
                if not all_chunks:
                    raise RuntimeError(f"文档《{document.title}》没有可用文本块")
                chunk_batches = _complete_chunk_batches(all_chunks)
                history_chunks = _evenly_sample(all_chunks, WIKI_CHUNKS_PER_BATCH)
                historical_nodes = await history_resolver.retrieve(
                    document,
                    history_chunks,
                    limit=16,
                )
                historical_candidates_used += len(historical_nodes)
                generated_batches: list[tuple[GeneratedWikiGraph, list[Chunk]]] = []
                document_recovery_batches = 0
                cited_chunk_ids: set[uuid.UUID] = set()
                for batch_index, chunks in enumerate(chunk_batches, 1):
                    batch_results: list[tuple[GeneratedWikiGraph, list[Chunk]]] = []
                    job.change_summary = (
                        f"正在分析文档 {document_index}/{len(documents)}：{document.title}；"
                        f"材料批次 {batch_index}/{len(chunk_batches)}，正在结构化抽取"
                    )
                    job.quality_report = {
                        **job.quality_report,
                        "current_document": {
                            "document_id": str(document.id),
                            "document_title": document.title,
                            "document_index": document_index,
                            "document_count": len(documents),
                            "batch_index": batch_index,
                            "batch_count": len(chunk_batches),
                            "attempt": "normal",
                        },
                    }
                    await session.commit()
                    try:
                        generated = await _generate_document_graph(
                            provider,
                            knowledge_base,
                            document,
                            chunks,
                            historical_nodes=historical_nodes,
                            batch_index=batch_index,
                            batch_count=len(chunk_batches),
                        )
                        batch_results.append((generated, chunks))
                    except Exception as first_exc:
                        job.change_summary = (
                            f"正在分析文档 {document_index}/{len(documents)}：{document.title}；"
                            f"材料批次 {batch_index}/{len(chunk_batches)}，正在紧凑重试"
                        )
                        job.quality_report = {
                            **job.quality_report,
                            "current_document": {
                                **job.quality_report.get("current_document", {}),
                                "attempt": "compact_retry",
                                "last_error": f"{type(first_exc).__name__}: {first_exc}"[:500],
                            },
                        }
                        await session.commit()
                        try:
                            generated = await _generate_document_graph(
                                provider,
                                knowledge_base,
                                document,
                                chunks,
                                historical_nodes=historical_nodes,
                                compact=True,
                                batch_index=batch_index,
                                batch_count=len(chunk_batches),
                            )
                            retried_documents.append(
                                {
                                    "document_id": str(document.id),
                                    "document_title": document.title,
                                    "batch_index": batch_index,
                                    "first_error": (f"{type(first_exc).__name__}: {first_exc}")[
                                        :500
                                    ],
                                }
                            )
                            batch_results.append((generated, chunks))
                        except Exception as retry_exc:
                            recovery_batches = _complete_chunk_batches(
                                chunks,
                                WIKI_RECOVERY_CHUNKS_PER_BATCH,
                            )
                            job.change_summary = (
                                f"正在分析文档 {document_index}/{len(documents)}："
                                f"{document.title}；"
                                f"材料批次 {batch_index}/{len(chunk_batches)}，"
                                f"已缩小为 {len(recovery_batches)} 个子批次"
                            )
                            job.quality_report = {
                                **job.quality_report,
                                "current_document": {
                                    **job.quality_report.get("current_document", {}),
                                    "attempt": "recovery_batches",
                                    "recovery_batch_count": len(recovery_batches),
                                    "last_error": f"{type(retry_exc).__name__}: {retry_exc}"[:500],
                                },
                            }
                            await session.commit()
                            try:
                                for recovery_index, recovery_chunks in enumerate(
                                    recovery_batches,
                                    1,
                                ):
                                    recovered = await _generate_document_graph(
                                        provider,
                                        knowledge_base,
                                        document,
                                        recovery_chunks,
                                        historical_nodes=historical_nodes,
                                        compact=True,
                                        batch_index=recovery_index,
                                        batch_count=len(recovery_batches),
                                    )
                                    batch_results.append((recovered, recovery_chunks))
                            except Exception as recovery_exc:
                                raise RuntimeError(
                                    f"Wiki 文档《{document.title}》第 {batch_index} 个材料批次"
                                    "在缩小到 4 个文本块后仍无法完成结构化抽取；"
                                    f"首次：{type(first_exc).__name__}: {str(first_exc)[:180]}；"
                                    f"紧凑重试：{type(retry_exc).__name__}: "
                                    f"{str(retry_exc)[:180]}；"
                                    f"最小批次：{type(recovery_exc).__name__}: "
                                    f"{str(recovery_exc)[:180]}"
                                ) from recovery_exc
                            document_recovery_batches += 1
                            recovered_batches.append(
                                {
                                    "document_id": str(document.id),
                                    "document_title": document.title,
                                    "batch_index": batch_index,
                                    "recovery_batch_count": len(recovery_batches),
                                    "retry_error": (f"{type(retry_exc).__name__}: {retry_exc}")[
                                        :500
                                    ],
                                    "first_error": (f"{type(first_exc).__name__}: {first_exc}")[
                                        :500
                                    ],
                                }
                            )
                            logger.warning(
                                "wiki_document_generation_recovered",
                                document_id=str(document.id),
                                batch_index=batch_index,
                                recovery_batch_count=len(recovery_batches),
                            )
                    generated_batches.extend(batch_results)
                    job.change_summary = (
                        f"正在分析文档 {document_index}/{len(documents)}：{document.title}；"
                        f"材料批次 {batch_index}/{len(chunk_batches)}"
                    )
                    job.quality_report = {
                        **job.quality_report,
                        "current_document": {
                            "document_id": str(document.id),
                            "document_title": document.title,
                            "document_index": document_index,
                            "document_count": len(documents),
                            "batch_index": batch_index,
                            "batch_count": len(chunk_batches),
                        },
                    }
                    await session.commit()

                historical_by_page = {item.page_id: item for item in historical_nodes}
                for generated, chunks in generated_batches:
                    generated_by_key = {node.key: node for node in generated.nodes}
                    slug_by_key: dict[str, str] = {}
                    for node in generated.nodes:
                        original_title = node.title
                        node.title = canonicalize_wiki_entity_title(
                            node.title,
                            node_type=node.node_type,
                        )
                        historical = (
                            historical_by_page.get(node.existing_page_id)
                            if node.existing_page_id is not None
                            else None
                        )
                        if historical is None:
                            historical = await resolve_exact_alias(
                                session,
                                space_id=space.id,
                                node_type=node.node_type,
                                title=node.title,
                            )
                        if historical is not None:
                            slug = historical.slug
                            canonical_title = canonicalize_wiki_entity_title(
                                historical.title,
                                node_type=historical.node_type,
                            )
                            canonical_type = historical.node_type
                            reused_history_pages.add(historical.page_id)
                        else:
                            slug = _node_slug(node.node_type, node.title)
                            canonical_title = node.title
                            canonical_type = node.node_type
                        slug_by_key[node.key] = slug
                        aggregate = aggregates.setdefault(
                            slug,
                            _NodeAggregate(
                                node_type=canonical_type,
                                title=canonical_title,
                                summary=node.summary,
                            ),
                        )
                        aggregate.sections.append(
                            (document.title, node.markdown.strip(), document.source_time)
                        )
                        aggregate.aliases.update(
                            wiki_label_aliases(original_title, node_type=canonical_type)
                        )
                        references = [
                            reference
                            for reference in node.source_refs
                            if 1 <= reference <= len(chunks)
                        ] or list(range(1, len(chunks) + 1))
                        for reference in references:
                            if 1 <= reference <= len(chunks):
                                chunk = chunks[reference - 1]
                                cited_chunk_ids.add(chunk.id)
                                aggregate.sources[chunk.id] = (document, chunk)
                    for generated_relation in generated.relations:
                        source_node = generated_by_key[generated_relation.source_key]
                        target_node = generated_by_key[generated_relation.target_key]
                        relation_chunks = [
                            chunks[index - 1]
                            for index in generated_relation.source_refs
                            if 1 <= index <= len(chunks)
                        ]
                        source_times = [
                            item.source_time
                            for item in relation_chunks
                            if item.source_time is not None
                        ]
                        relations.append(
                            _RelationAggregate(
                                source_slug=slug_by_key[source_node.key],
                                target_slug=slug_by_key[target_node.key],
                                relation_type=generated_relation.relation_type,
                                evidence=generated_relation.evidence,
                                source_document_id=document.id,
                                source_time=(
                                    max(source_times) if source_times else document.source_time
                                ),
                            )
                        )

                produced_node_count = sum(
                    len(generated.nodes) for generated, _chunks in generated_batches
                )
                produced_relation_count = sum(
                    len(generated.relations) for generated, _chunks in generated_batches
                )
                coverage_documents.append(
                    {
                        "document_id": str(document.id),
                        "document_title": document.title,
                        "active_chunk_count": len(all_chunks),
                        "analyzed_chunk_count": sum(len(batch) for batch in chunk_batches),
                        "cited_chunk_count": len(cited_chunk_ids),
                        "batch_count": len(chunk_batches),
                        "recovery_batch_count": document_recovery_batches,
                        "produced_node_count": produced_node_count,
                        "produced_relation_count": produced_relation_count,
                        "status": ("processed" if produced_node_count else "processed_no_entity"),
                    }
                )
                job.quality_report = {
                    **job.quality_report,
                    "document_coverage": {
                        "expected_document_count": len(documents),
                        "processed_document_count": document_index,
                        "expected_document_ids": expected_document_ids,
                        "documents": coverage_documents,
                    },
                }
                job.change_summary = (
                    f"正在分析文档 {document_index}/{len(documents)}：{document.title}；"
                    f"已覆盖 {len(all_chunks)} 个文本块"
                )
                await session.commit()

            if not aggregates:
                job.change_summary = (
                    f"已完整分析 {len(documents)} 份文档，未发现可持续维护的稳定 Wiki 实体"
                )
                job.quality_report = {
                    **job.quality_report,
                    "current_document": None,
                    "recovered_batches": recovered_batches,
                    "retried_documents": retried_documents,
                    "history_resolution": {
                        "candidate_count": historical_candidates_used,
                        "reused_page_count": len(reused_history_pages),
                        "embedding_error": history_embedding_error,
                        "max_candidates_per_document": 16,
                    },
                    "checked_pages": 0,
                    "covered_document_count": len(documents),
                    "failures": [],
                }
                job.candidate_version = space.published_version
                job.status = "published"
                await mark_job_documents_succeeded(session, job_id=job.id)
                await session.commit()
                return
            relations_by_source: dict[str, list[_RelationAggregate]] = {}
            for aggregate_relation in relations:
                relations_by_source.setdefault(aggregate_relation.source_slug, []).append(
                    aggregate_relation
                )

            for slug, aggregate in aggregates.items():
                if len(aggregate.sections) == 1:
                    content = aggregate.sections[0][1]
                else:
                    sections = [
                        (
                            f"## 来自《{document_title}》"
                            f"（{source_time.isoformat() if source_time else '时间未知'}）\n\n"
                            f"{markdown}"
                        )
                        for document_title, markdown, source_time in aggregate.sections
                    ]
                    content = f"# {aggregate.title}\n\n" + "\n\n---\n\n".join(sections)
                if len(content.strip()) < 50 and aggregate.sources:
                    source_document, source_chunk = next(iter(aggregate.sources.values()))
                    content = (
                        f"{content.strip()}\n\n## 来源摘录\n\n"
                        f"{source_chunk.content[:500].strip()}\n\n"
                        f"> 来源：《{source_document.title}》"
                    )
                page = await session.scalar(
                    select(WikiPage).where(
                        WikiPage.space_id == space.id,
                        WikiPage.slug == slug,
                    )
                )
                if page is None:
                    page = WikiPage(
                        space_id=space.id,
                        slug=slug,
                        title=aggregate.title,
                        summary=aggregate.summary or content[:300],
                        source_time=None,
                    )
                    session.add(page)
                    await session.flush()
                else:
                    page.title = aggregate.title
                    page.is_archived = False
                    page.merged_into_page_id = None
                previous = (
                    await session.get(WikiPageVersion, page.current_version_id)
                    if page.current_version_id
                    else None
                )
                protected = list(previous.protected_blocks) if previous else []
                previous_sources: list[WikiPageSource] = []
                if previous is not None and job.affected_document_ids:
                    previous_sources = list(
                        (
                            await session.scalars(
                                select(WikiPageSource).where(
                                    WikiPageSource.page_version_id == previous.id
                                )
                            )
                        ).all()
                    )
                    previous_body = previous.content.strip()
                    if previous_body and previous_body != content.strip():
                        content = f"{previous_body}\n\n---\n\n## 增量更新\n\n{content.strip()}"
                if protected and not all(block in content for block in protected):
                    content += "\n\n" + "\n\n".join(protected)
                node_source_times: list[datetime] = []
                for document, chunk in aggregate.sources.values():
                    candidate_time = chunk.source_time or document.source_time
                    if candidate_time is not None:
                        node_source_times.append(candidate_time)
                node_source_time = max(node_source_times) if node_source_times else None
                version_number = (
                    await session.scalar(
                        select(func.max(WikiPageVersion.version_number)).where(
                            WikiPageVersion.page_id == page.id
                        )
                    )
                    or 0
                ) + 1
                version = WikiPageVersion(
                    page_id=page.id,
                    version_number=version_number,
                    content=content,
                    protected_blocks=protected,
                    generation_id=job.generation_id,
                    change_summary=f"聚合 {len(aggregate.sections)} 段来源内容生成节点",
                    source_time=node_source_time,
                    metadata_json={
                        "node_type": aggregate.node_type,
                        "node_slug": slug,
                        "aliases": sorted(aggregate.aliases),
                        "relations": [
                            {
                                "target_slug": relation.target_slug,
                                "type": relation.relation_type,
                                "evidence": relation.evidence,
                                "source_document_id": str(relation.source_document_id),
                                "source_time": (
                                    relation.source_time.isoformat()
                                    if relation.source_time is not None
                                    else None
                                ),
                            }
                            for relation in relations_by_source.get(slug, [])
                        ],
                    },
                )
                session.add(version)
                await session.flush()
                copied_sources: set[tuple[uuid.UUID, uuid.UUID | None, str]] = set()
                for old_source in previous_sources:
                    source_key = (
                        old_source.document_id,
                        old_source.chunk_id,
                        old_source.paragraph_key,
                    )
                    if source_key in copied_sources:
                        continue
                    copied_sources.add(source_key)
                    session.add(
                        WikiPageSource(
                            page_version_id=version.id,
                            document_id=old_source.document_id,
                            chunk_id=old_source.chunk_id,
                            paragraph_key=old_source.paragraph_key,
                            evidence_text=old_source.evidence_text,
                            source_time=old_source.source_time,
                        )
                    )
                for document, chunk in aggregate.sources.values():
                    source_key = (
                        document.id,
                        chunk.id,
                        f"{str(document.id)[:8]}-{chunk.ordinal}",
                    )
                    if source_key in copied_sources:
                        continue
                    copied_sources.add(source_key)
                    session.add(
                        WikiPageSource(
                            page_version_id=version.id,
                            document_id=document.id,
                            chunk_id=chunk.id,
                            paragraph_key=f"{str(document.id)[:8]}-{chunk.ordinal}",
                            evidence_text=chunk.content[:4000],
                            source_time=chunk.source_time or document.source_time,
                        )
                    )
                await session.commit()
            job.change_summary = (
                f"从 {len(documents)} 份文档生成/更新 {len(aggregates)} 个 Wiki 节点"
                + (
                    f"，其中 {len(recovered_batches)} 个材料批次经缩小后恢复"
                    if recovered_batches
                    else ""
                )
            )
            job.quality_report = {
                **job.quality_report,
                "current_document": None,
                "fallback_documents": [],
                "recovered_batches": recovered_batches,
                "retried_documents": retried_documents,
                "history_resolution": {
                    "candidate_count": historical_candidates_used,
                    "reused_page_count": len(reused_history_pages),
                    "embedding_error": history_embedding_error,
                    "max_candidates_per_document": 16,
                },
            }
            job.status = "quality_check"
            await session.commit()
            await publish_generation(session, job.id)
        except Exception as exc:
            await session.rollback()
            job = await session.get(WikiUpdateJob, job_id)
            if job and job.status not in {"published", "cancelled"}:
                error_summary = f"{type(exc).__name__}: {exc}"[:1000]
                if job.status != "quality_failed":
                    job.status = "failed"
                    job.error_summary = error_summary
                await mark_job_documents_failed(
                    session,
                    job=job,
                    document_ids=selected_document_ids or job_expected_document_ids(job),
                    error_summary=error_summary,
                )
                await session.commit()
            raise
        finally:
            if history_resolver is not None:
                await history_resolver.close()
            await provider.close()


async def _rebuild_generation_graph(
    session: AsyncSession,
    space: WikiSpace,
    versions: list[WikiPageVersion],
) -> None:
    records: list[tuple[WikiPage, WikiPageVersion, list[Document]]] = []
    page_ids: list[uuid.UUID] = []
    for version in versions:
        page = await session.get(WikiPage, version.page_id)
        if page is None:
            continue
        document_ids = list(
            dict.fromkeys(
                (
                    await session.scalars(
                        select(WikiPageSource.document_id).where(
                            WikiPageSource.page_version_id == version.id
                        )
                    )
                ).all()
            )
        )
        documents = [
            document
            for document_id in document_ids
            if (document := await session.get(Document, document_id)) is not None
        ]
        records.append((page, version, documents))
        page_ids.append(page.id)

    if page_ids:
        await session.execute(
            delete(WikiEdge).where(
                WikiEdge.space_id == space.id,
                WikiEdge.source_page_id.in_(page_ids),
            )
        )

    node_by_slug: dict[str, WikiNode] = {}
    for page, version, documents in records:
        metadata = version.metadata_json
        node_type = str(metadata.get("node_type") or "page")[:30]
        page_node = await session.scalar(
            select(WikiNode).where(
                WikiNode.space_id == space.id,
                WikiNode.page_id == page.id,
            )
        )
        first_document = documents[0] if documents else None
        if page_node is None:
            page_node = WikiNode(
                space_id=space.id,
                node_type=node_type,
                label=page.title,
                page_id=page.id,
                source_document_id=first_document.id if first_document else None,
                source_page_id=page.id,
                source_time=version.source_time,
                metadata_json={"slug": page.slug},
            )
            session.add(page_node)
        else:
            page_node.node_type = node_type
            page_node.label = page.title
            page_node.source_document_id = first_document.id if first_document else None
            page_node.source_page_id = page.id
            page_node.source_time = version.source_time
            page_node.metadata_json = {**page_node.metadata_json, "slug": page.slug}
        # Search vectors are derived from the page title and summary. Publishing
        # a new version can change either, so never leave a stale vector attached
        # to the rebuilt node. The publisher refreshes it after the atomic switch.
        page_node.embedding = None
        page_node.embedding_model_id = None
        node_by_slug[page.slug] = page_node

    await session.flush()
    for page, version, _documents in records:
        await add_node_alias(
            session,
            node=node_by_slug[page.slug],
            alias=page.title,
            source="canonical",
        )
        raw_aliases = version.metadata_json.get("aliases", [])
        if isinstance(raw_aliases, list):
            for raw_alias in raw_aliases:
                alias = str(raw_alias).strip()
                if alias:
                    await add_node_alias(
                        session,
                        node=node_by_slug[page.slug],
                        alias=alias,
                        source="generation",
                    )
    for page, version, documents in records:
        page_node = node_by_slug[page.slug]
        for document in documents:
            document_node = await session.scalar(
                select(WikiNode).where(
                    WikiNode.space_id == space.id,
                    WikiNode.document_id == document.id,
                )
            )
            if document_node is None:
                document_node = WikiNode(
                    space_id=space.id,
                    node_type="document",
                    label=document.title,
                    document_id=document.id,
                    source_document_id=document.id,
                    source_time=document.source_time,
                )
                session.add(document_node)
                await session.flush()
            else:
                document_node.label = document.title
                document_node.source_time = document.source_time
            session.add(
                WikiEdge(
                    space_id=space.id,
                    source_node_id=page_node.id,
                    target_node_id=document_node.id,
                    edge_type="sourced_from",
                    evidence=f"节点《{page.title}》来源于文档《{document.title}》",
                    source_document_id=document.id,
                    source_page_id=page.id,
                    source_time=document.source_time or version.source_time,
                )
            )

    relation_keys: set[tuple[uuid.UUID, uuid.UUID, str, str]] = set()
    for page, version, _documents in records:
        source_node = node_by_slug[page.slug]
        raw_relations = version.metadata_json.get("relations", [])
        if not isinstance(raw_relations, list):
            continue
        for raw_relation in raw_relations:
            if not isinstance(raw_relation, dict):
                continue
            target_slug = str(raw_relation.get("target_slug") or "")
            target_node = node_by_slug.get(target_slug)
            if target_node is None:
                target_page = await session.scalar(
                    select(WikiPage).where(
                        WikiPage.space_id == space.id,
                        WikiPage.slug == target_slug,
                        WikiPage.current_version_id.is_not(None),
                    )
                )
                if target_page is not None:
                    target_node = await session.scalar(
                        select(WikiNode).where(
                            WikiNode.space_id == space.id,
                            WikiNode.page_id == target_page.id,
                        )
                    )
            if target_node is None or target_node.id == source_node.id:
                continue
            edge_type = str(raw_relation.get("type") or "related_to")[:40]
            evidence = str(raw_relation.get("evidence") or "存在来源支持的关联")[:4000]
            relation_key = (source_node.id, target_node.id, edge_type, evidence)
            if relation_key in relation_keys:
                continue
            relation_keys.add(relation_key)
            raw_document_id = raw_relation.get("source_document_id")
            try:
                source_document_id = uuid.UUID(str(raw_document_id)) if raw_document_id else None
            except ValueError:
                source_document_id = None
            raw_source_time = raw_relation.get("source_time")
            try:
                source_time = (
                    datetime.fromisoformat(str(raw_source_time)) if raw_source_time else None
                )
            except ValueError:
                source_time = version.source_time
            session.add(
                WikiEdge(
                    space_id=space.id,
                    source_node_id=source_node.id,
                    target_node_id=target_node.id,
                    edge_type=edge_type,
                    evidence=evidence,
                    source_document_id=source_document_id,
                    source_page_id=page.id,
                    source_time=source_time or version.source_time,
                )
            )
