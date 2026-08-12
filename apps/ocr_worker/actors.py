from __future__ import annotations

import asyncio
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

import aiofiles
import dramatiq
from synapsekb.config import get_settings
from synapsekb.database.models import Document, ProcessingJob
from synapsekb.database.session import AsyncSessionFactory
from synapsekb.document_processing.ocr_config import load_paddle_ocr_config
from synapsekb.document_processing.paddleocr import OcrCancelled, PaddleOcrCloudClient
from synapsekb.storage.factory import create_runtime_storage
from synapsekb.tasks.broker import broker
from synapsekb.tasks.quota import distributed_quota

dramatiq.set_broker(broker)


async def _run_ocr(job_id: uuid.UUID) -> None:
    async with AsyncSessionFactory() as session:
        ocr_config = await load_paddle_ocr_config(session)
        if not ocr_config.api_key:
            raise RuntimeError("PaddleOCR Access Token 未配置")
        job = await session.get(ProcessingJob, job_id)
        if job is None or job.cancel_requested_at is not None:
            return
        document = await session.get(Document, job.document_id)
        if document is None:
            return
        storage = await create_runtime_storage(session)
        job.status = "running"
        job.stage = "ocr"
        job.progress = 0.15
        job.attempt += 1
        await session.commit()

        with tempfile.TemporaryDirectory(prefix="synapsekb-ocr-") as temp_dir:
            source = Path(temp_dir) / "source.pdf"
            async with aiofiles.open(source, "wb") as handle:
                async for chunk in storage.iter_bytes(document.object_key):
                    await handle.write(chunk)
            client = PaddleOcrCloudClient(
                base_url=ocr_config.base_url,
                api_key=ocr_config.api_key,
                timeout_seconds=ocr_config.timeout_seconds,
            )

            async def is_cancelled() -> bool:
                await session.refresh(job)
                return job.cancel_requested_at is not None

            try:
                async with distributed_quota(
                    redis_url=get_settings().redis_url,
                    key="quota:ocr:paddle",
                    limit=ocr_config.max_concurrency,
                    timeout_seconds=ocr_config.timeout_seconds,
                    is_cancelled=is_cancelled,
                ):
                    task_id = job.external_task_id
                    if task_id is None:
                        task_id = await client.submit(source, model=ocr_config.default_model)
                        job.external_task_id = task_id
                        job.metadata_json = {
                            **job.metadata_json,
                            "ocr_model": ocr_config.default_model,
                        }
                        await session.commit()
                    submitted_model = str(
                        job.metadata_json.get("ocr_model") or ocr_config.default_model
                    )
                    result = await client.wait(
                        task_id,
                        model=submitted_model,
                        timeout_seconds=ocr_config.timeout_seconds,
                        is_cancelled=is_cancelled,
                    )
            except (OcrCancelled, asyncio.CancelledError):
                job.status = "cancelled"
                document.status = "cancelled"
                job.finished_at = datetime.now(UTC)
                await session.commit()
                return
            finally:
                await client.close()

            await session.refresh(job)
            if job.cancel_requested_at is not None:
                job.status = "cancelled"
                document.status = "cancelled"
                job.finished_at = datetime.now(UTC)
                await session.commit()
                return
            parsed = Path(temp_dir) / "ocr.md"
            async with aiofiles.open(parsed, "w", encoding="utf-8") as text_handle:
                await text_handle.write(result.markdown)
            key = f"parsed/{document.knowledge_base_id}/{document.id}.md"
            await storage.put_file(key, parsed, "text/markdown")
            document.parsed_text_key = key
            document.page_count = result.page_count
            job.metadata_json = {**job.metadata_json, **result.metadata}
            job.status = "queued"
            job.stage = "ocr_completed"
            job.progress = 0.3
            await session.commit()
    from apps.document_worker.actors import process_document

    process_document.send(str(job_id))


@dramatiq.actor(
    queue_name="ocr",
    max_retries=3,
    min_backoff=10_000,
    max_backoff=120_000,
    time_limit=1_200_000,
)
def process_ocr(job_id: str) -> None:
    parsed_id = uuid.UUID(job_id)
    try:
        asyncio.run(_run_ocr(parsed_id))
    except Exception as exc:
        asyncio.run(_mark_ocr_failed(parsed_id, exc))
        raise


async def _mark_ocr_failed(job_id: uuid.UUID, exc: Exception) -> None:
    async with AsyncSessionFactory() as session:
        job = await session.get(ProcessingJob, job_id)
        if job is None or job.status in {"succeeded", "cancelled"}:
            return
        document = await session.get(Document, job.document_id)
        summary = f"{type(exc).__name__}: {exc}"[:1000]
        job.status = "failed"
        job.error_summary = summary
        job.finished_at = datetime.now(UTC)
        if document is not None:
            document.status = "failed"
            document.error_summary = summary
        await session.commit()
