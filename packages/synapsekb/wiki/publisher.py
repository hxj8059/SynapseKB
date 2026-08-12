from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from synapsekb.database.models import (
    Document,
    WikiEdge,
    WikiNode,
    WikiPage,
    WikiPageSource,
    WikiPageVersion,
    WikiSpace,
    WikiUpdateJob,
)


class WikiQualityError(RuntimeError):
    pass


async def publish_generation(
    session: AsyncSession,
    job_id: uuid.UUID,
) -> None:
    """Atomically switch all pages produced by one generation."""

    job = await session.scalar(
        select(WikiUpdateJob).where(WikiUpdateJob.id == job_id).with_for_update()
    )
    if job is None:
        raise WikiQualityError("Wiki 更新任务不存在")
    if job.status == "published":
        return
    if job.cancel_requested_at is not None:
        job.status = "cancelled"
        await session.commit()
        return
    space = await session.scalar(
        select(WikiSpace).where(WikiSpace.id == job.space_id).with_for_update()
    )
    if space is None or job.candidate_version is None:
        raise WikiQualityError("Wiki 候选版本不完整")

    versions = list(
        (
            await session.scalars(
                select(WikiPageVersion).where(WikiPageVersion.generation_id == job.generation_id)
            )
        ).all()
    )
    if not versions:
        raise WikiQualityError("候选版本没有页面")
    failures: list[str] = []
    coverage = job.quality_report.get("document_coverage", {})
    if not isinstance(coverage, dict):
        coverage = {}
    raw_expected_ids = coverage.get("expected_document_ids", [])
    expected_document_ids: set[uuid.UUID] = set()
    if isinstance(raw_expected_ids, list):
        for value in raw_expected_ids:
            try:
                expected_document_ids.add(uuid.UUID(str(value)))
            except ValueError:
                failures.append(f"覆盖报告包含无效文档 ID：{value}")
    raw_coverage_documents = coverage.get("documents", [])
    processed_document_ids: set[uuid.UUID] = set()
    documents_requiring_sources: set[uuid.UUID] = set()
    if isinstance(raw_coverage_documents, list):
        for item in raw_coverage_documents:
            if not isinstance(item, dict):
                continue
            try:
                document_id = uuid.UUID(str(item.get("document_id")))
            except ValueError:
                continue
            if item.get("status") in {"processed", "processed_no_entity"}:
                processed_document_ids.add(document_id)
            if int(item.get("produced_node_count", 0) or 0) > 0:
                documents_requiring_sources.add(document_id)
            if int(item.get("active_chunk_count", 0) or 0) != int(
                item.get("analyzed_chunk_count", 0) or 0
            ):
                failures.append(f"文档 {document_id} 尚未覆盖全部文本块")
    missing_processed = expected_document_ids - processed_document_ids
    if missing_processed:
        failures.append(f"仍有 {len(missing_processed)} 份文档未完成 Wiki 分析")
    for version in versions:
        if len(version.content.strip()) < 50:
            failures.append(f"页面版本 {version.id} 内容过短")
        source_count = await session.scalar(
            select(func.count())
            .select_from(WikiPageSource)
            .where(WikiPageSource.page_version_id == version.id)
        )
        if not version.is_manual and not source_count:
            failures.append(f"页面版本 {version.id} 缺少引用")
    candidate_source_document_ids = set(
        (
            await session.scalars(
                select(WikiPageSource.document_id)
                .join(
                    WikiPageVersion,
                    WikiPageVersion.id == WikiPageSource.page_version_id,
                )
                .where(WikiPageVersion.generation_id == job.generation_id)
            )
        ).all()
    )
    missing_sources = documents_requiring_sources - candidate_source_document_ids
    if missing_sources:
        failures.append(f"仍有 {len(missing_sources)} 份文档没有进入候选 Wiki 来源")
    job.quality_report = {
        **job.quality_report,
        "checked_pages": len(versions),
        "covered_document_count": len(processed_document_ids),
        "failures": failures,
        "checked_at": datetime.now(UTC).isoformat(),
    }
    if failures:
        job.status = "quality_failed"
        job.error_summary = "; ".join(failures)[:1000]
        await session.commit()
        raise WikiQualityError("; ".join(failures))

    # Import locally to avoid a module cycle: the generator calls this publisher.
    # Graph mutations remain inside the same transaction as the page pointer switch.
    from synapsekb.wiki.generator import _rebuild_generation_graph

    candidate_page_ids = {version.page_id for version in versions}
    if not job.affected_document_ids:
        stale_pages = list(
            (
                await session.scalars(
                    select(WikiPage).where(
                        WikiPage.space_id == space.id,
                        WikiPage.current_version_id.is_not(None),
                        WikiPage.id.not_in(candidate_page_ids),
                    )
                )
            ).all()
        )
        for stale_page in stale_pages:
            stale_page.current_version_id = None
        await session.execute(delete(WikiEdge).where(WikiEdge.space_id == space.id))
        await session.execute(delete(WikiNode).where(WikiNode.space_id == space.id))

    for version in versions:
        page = await session.get(WikiPage, version.page_id)
        if page is None:
            raise WikiQualityError(f"页面 {version.page_id} 不存在")
        source_document_ids = set(
            (
                await session.scalars(
                    select(WikiPageSource.document_id).where(
                        WikiPageSource.page_version_id == version.id
                    )
                )
            ).all()
        )
        for document_id in source_document_ids:
            document = await session.get(Document, document_id)
            if document is None:
                raise WikiQualityError(f"来源文档 {document_id} 不存在")
        page.current_version_id = version.id
        page.source_time = version.source_time
        page.summary = version.content[:300]
    await _rebuild_generation_graph(session, space, versions)
    space.published_version = job.candidate_version
    job.status = "published"
    await session.commit()
