from __future__ import annotations

import asyncio
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

import aiofiles
import structlog
from sqlalchemy import delete, func, select, text

from synapsekb.database.models import (
    Chunk,
    Document,
    KnowledgeBase,
    ProcessingJob,
    ProviderModel,
)
from synapsekb.database.session import AsyncSessionFactory
from synapsekb.document_processing.chunker import HeadingAwareChunker
from synapsekb.document_processing.keyword import tokenize_for_postgres
from synapsekb.document_processing.parsers import NeedsOcrError, parse_document
from synapsekb.models.provider import create_provider
from synapsekb.storage.base import ObjectStorage
from synapsekb.storage.factory import create_runtime_storage
from synapsekb.temporal.source_time import extract_source_time
from synapsekb.wiki.scheduler import schedule_wiki_update

logger = structlog.get_logger()


class JobCancelled(RuntimeError):
    pass


async def _download_to(storage: ObjectStorage, storage_key: str, path: Path) -> None:
    async with aiofiles.open(path, "wb") as handle:
        async for chunk in storage.iter_bytes(storage_key):
            await handle.write(chunk)


async def _check_cancelled(job_id: uuid.UUID) -> None:
    async with AsyncSessionFactory() as session:
        cancelled = await session.scalar(
            select(ProcessingJob.cancel_requested_at).where(ProcessingJob.id == job_id)
        )
        if cancelled is not None:
            raise JobCancelled


async def _set_status(
    job_id: uuid.UUID,
    *,
    status: str,
    stage: str,
    progress: float,
    error_summary: str | None = None,
) -> None:
    async with AsyncSessionFactory() as session:
        job = await session.get(ProcessingJob, job_id)
        if job is None:
            return
        job.status = status
        job.stage = stage
        job.progress = progress
        job.error_summary = error_summary
        if status == "running" and job.started_at is None:
            job.started_at = datetime.now(UTC)
        if status in {"succeeded", "failed", "cancelled"}:
            job.finished_at = datetime.now(UTC)
        await session.commit()


async def process_document_job(job_id: uuid.UUID) -> str:
    """Idempotently parse and index a document.

    Returns `waiting_ocr` when ownership is handed to the OCR queue.
    """

    async with AsyncSessionFactory() as session:
        locked = await session.scalar(
            text("SELECT pg_try_advisory_lock(hashtext(:key))").bindparams(key=str(job_id))
        )
        if not locked:
            return "already_running"
        try:
            job = await session.get(ProcessingJob, job_id)
            if job is None or job.status in {"succeeded", "cancelled"}:
                return "done"
            document = await session.get(Document, job.document_id)
            if document is None:
                return "missing_document"
            if job.cancel_requested_at is not None:
                job.status = "cancelled"
                document.status = "cancelled"
                await session.commit()
                return "cancelled"
            storage = await create_runtime_storage(session)
            job.status = "running"
            job.stage = "downloading"
            job.progress = 0.05
            job.attempt += 1
            job.started_at = job.started_at or datetime.now(UTC)
            document.status = "processing"
            await session.commit()

            with tempfile.TemporaryDirectory(prefix="synapsekb-doc-") as temp_dir:
                source_path = Path(temp_dir) / "source"
                await _download_to(storage, document.object_key, source_path)
                await _check_cancelled(job_id)

                if document.parsed_text_key:
                    markdown = (await storage.read(document.parsed_text_key)).decode("utf-8")
                else:
                    await _set_status(
                        job_id,
                        status="running",
                        stage="parsing",
                        progress=0.15,
                    )
                    try:
                        parsed = await asyncio.to_thread(
                            parse_document,
                            source_path,
                            document.filename,
                            document.media_type,
                        )
                    except NeedsOcrError:
                        job = await session.get(ProcessingJob, job_id)
                        if job is not None:
                            job.status = "queued"
                            job.stage = "waiting_ocr"
                            job.progress = 0.1
                            await session.commit()
                        return "waiting_ocr"
                    markdown = parsed.markdown
                    document.page_count = parsed.page_count

                await _check_cancelled(job_id)
                parsed_key = f"parsed/{document.knowledge_base_id}/{document.id}.md"
                parsed_path = Path(temp_dir) / "parsed.md"
                async with aiofiles.open(parsed_path, "w", encoding="utf-8") as handle:
                    await handle.write(markdown)
                await storage.put_file(parsed_key, parsed_path, "text/markdown")
                document.parsed_text_key = parsed_key
                if document.source_time is None:
                    document.source_time = extract_source_time(
                        filename=document.filename,
                        content=markdown,
                    )
                await session.commit()

                await _set_status(
                    job_id,
                    status="running",
                    stage="chunking",
                    progress=0.35,
                )
                chunks = await asyncio.to_thread(HeadingAwareChunker().split, markdown)
                if not chunks:
                    raise ValueError("文档没有可索引文本")

                knowledge_base = await session.get(KnowledgeBase, document.knowledge_base_id)
                if knowledge_base is None or knowledge_base.embedding_model_id is None:
                    raise RuntimeError("知识库尚未配置 Embedding 模型")
                model = await session.get(ProviderModel, knowledge_base.embedding_model_id)
                if model is None or model.kind != "embedding" or not model.is_enabled:
                    raise RuntimeError("Embedding 模型不可用")
                provider = create_provider(model)
                vectors: list[list[float]] = []
                try:
                    for start in range(0, len(chunks), 64):
                        await _check_cancelled(job_id)
                        batch = chunks[start : start + 64]
                        vectors.extend(
                            await provider.embeddings([chunk.content for chunk in batch])
                        )
                        await _set_status(
                            job_id,
                            status="running",
                            stage="embedding",
                            progress=0.4 + 0.45 * min((start + len(batch)) / len(chunks), 1),
                        )
                finally:
                    await provider.close()

                expected_dimensions = model.embedding_dimensions or 1536
                if any(len(vector) != expected_dimensions for vector in vectors):
                    raise RuntimeError(
                        f"Embedding 维度不匹配，配置 {expected_dimensions}，实际 "
                        f"{len(vectors[0]) if vectors else 0}"
                    )
                if expected_dimensions != 1536:
                    raise RuntimeError("当前迁移固定为 1536 维，请先执行维度迁移")

                await _check_cancelled(job_id)
                await session.execute(delete(Chunk).where(Chunk.document_id == document.id))
                for chunk, vector in zip(chunks, vectors, strict=True):
                    search_text = tokenize_for_postgres(chunk.content)
                    session.add(
                        Chunk(
                            knowledge_base_id=document.knowledge_base_id,
                            document_id=document.id,
                            ordinal=chunk.ordinal,
                            content=chunk.content,
                            search_text=search_text,
                            search_vector=func.to_tsvector("simple", search_text),
                            embedding=vector,
                            token_count=chunk.token_count,
                            page_from=chunk.page_from,
                            page_to=chunk.page_to,
                            section=chunk.section,
                            source_time=document.source_time,
                            status="active",
                        )
                    )
                document.status = "ready"
                document.error_summary = None
                job = await session.get(ProcessingJob, job_id)
                if job is None or job.cancel_requested_at is not None:
                    raise JobCancelled
                job.status = "succeeded"
                job.stage = "completed"
                job.progress = 1
                job.finished_at = datetime.now(UTC)
                await session.commit()
                await schedule_wiki_update(document.knowledge_base_id, document.id)
                return "succeeded"
        except JobCancelled:
            await session.rollback()
            job = await session.get(ProcessingJob, job_id)
            document = await session.get(Document, job.document_id) if job else None
            if job:
                job.status = "cancelled"
                job.finished_at = datetime.now(UTC)
            if document:
                document.status = "cancelled"
            await session.commit()
            return "cancelled"
        except Exception as exc:
            await session.rollback()
            summary = f"{type(exc).__name__}: {exc}"[:1000]
            job = await session.get(ProcessingJob, job_id)
            document = await session.get(Document, job.document_id) if job else None
            if job:
                job.status = "failed"
                job.error_summary = summary
                job.finished_at = datetime.now(UTC)
            if document:
                document.status = "failed"
                document.error_summary = summary
            await session.commit()
            logger.exception("document_processing_failed", job_id=str(job_id))
            raise
        finally:
            await session.execute(
                text("SELECT pg_advisory_unlock(hashtext(:key))").bindparams(key=str(job_id))
            )
            await session.commit()
