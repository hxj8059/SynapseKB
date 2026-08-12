from __future__ import annotations

import hashlib
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

import aiofiles
import httpx
import structlog
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import AwareDatetime
from sqlalchemy import ColumnElement, and_, delete, exists, func, or_, select, update
from starlette.responses import Response

from apps.document_worker.actors import process_document
from synapsekb.api.schemas import (
    ChunkRead,
    DocumentRead,
    DocumentTagCreate,
    DocumentTagRead,
    DocumentUpdate,
    ProcessingJobRead,
    UploadCompleteRequest,
    UploadInitRequest,
    UploadInitResponse,
    UrlImportRequest,
)
from synapsekb.auth.dependencies import CurrentUser, DatabaseSession, DocumentWriteUser
from synapsekb.auth.policy import require_knowledge_base_access
from synapsekb.config import get_settings
from synapsekb.database.models import (
    AuditLog,
    Chunk,
    Document,
    DocumentTag,
    ProcessingJob,
    WikiEdge,
    WikiNode,
    WikiPage,
    WikiPageSource,
    document_tag_links,
)
from synapsekb.document_processing.url_fetcher import fetch_public_document
from synapsekb.document_processing.validation import safe_filename, validate_upload
from synapsekb.domain.enums import TimeField
from synapsekb.storage.factory import create_runtime_storage
from synapsekb.wiki.scheduler import schedule_wiki_update

router = APIRouter()
settings = get_settings()
logger = structlog.get_logger()


def _object_key(knowledge_base_id: uuid.UUID, document_id: uuid.UUID, filename: str) -> str:
    return f"originals/{knowledge_base_id}/{document_id}/{safe_filename(filename)}"


def _new_job(document: Document) -> ProcessingJob:
    generation = int(document.updated_at.timestamp() * 1_000_000)
    return ProcessingJob(
        document_id=document.id,
        job_type="parse",
        status="queued",
        idempotency_key=f"document:{document.id}:{generation}",
        progress=0,
        stage="queued",
    )


@router.get("", response_model=list[DocumentRead])
async def list_documents(
    user: CurrentUser,
    session: DatabaseSession,
    knowledge_base_id: uuid.UUID = Query(...),
    status_filter: str | None = Query(default=None, alias="status"),
    name: str | None = None,
    tag_ids: list[uuid.UUID] = Query(default=[]),
    time_field: TimeField = TimeField.SOURCE_TIME,
    from_time: AwareDatetime | None = None,
    to_time: AwareDatetime | None = None,
    include_unknown: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=10_000_000),
) -> list[Document]:
    await require_knowledge_base_access(session, user, knowledge_base_id)
    if from_time is not None and to_time is not None and to_time < from_time:
        raise HTTPException(status_code=422, detail="to_time 必须晚于 from_time")
    query = select(Document).where(Document.knowledge_base_id == knowledge_base_id)
    if status_filter:
        query = query.where(Document.status == status_filter)
    if name:
        query = query.where(Document.title.ilike(f"%{name}%"))
    if tag_ids:
        query = query.where(
            exists(
                select(document_tag_links.c.document_id).where(
                    document_tag_links.c.document_id == Document.id,
                    document_tag_links.c.tag_id.in_(tag_ids),
                )
            )
        )
    if from_time is not None or to_time is not None:
        column = {
            TimeField.SOURCE_TIME: Document.source_time,
            TimeField.CREATED_AT: Document.created_at,
            TimeField.UPDATED_AT: Document.updated_at,
        }[time_field]
        time_clauses: list[ColumnElement[bool]] = [column.is_not(None)]
        if from_time is not None:
            time_clauses.append(column >= from_time)
        if to_time is not None:
            time_clauses.append(column <= to_time)
        known = and_(*time_clauses)
        query = query.where(or_(known, column.is_(None)) if include_unknown else known)
    query = query.order_by(Document.updated_at.desc(), Document.id).offset(offset).limit(limit)
    return list((await session.scalars(query)).all())


@router.get("/count")
async def count_documents(
    user: CurrentUser,
    session: DatabaseSession,
    knowledge_base_id: uuid.UUID = Query(...),
) -> dict[str, int]:
    await require_knowledge_base_access(session, user, knowledge_base_id)
    count = await session.scalar(
        select(func.count(Document.id)).where(Document.knowledge_base_id == knowledge_base_id)
    )
    return {"count": int(count or 0)}


@router.post("/upload", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    user: DocumentWriteUser,
    session: DatabaseSession,
    knowledge_base_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    source_time: datetime | None = Form(default=None),
) -> Document:
    await require_knowledge_base_access(session, user, knowledge_base_id, write=True)
    if not file.filename:
        raise HTTPException(status_code=422, detail="缺少文件名")
    if source_time is not None and source_time.utcoffset() is None:
        raise HTTPException(status_code=422, detail="source_time 必须包含时区")

    temporary = tempfile.NamedTemporaryFile(prefix="synapsekb-upload-", delete=False)
    temporary_path = Path(temporary.name)
    temporary.close()
    size = 0
    digest = hashlib.sha256()
    first_bytes = b""
    try:
        async with aiofiles.open(temporary_path, "wb") as output:
            while chunk := await file.read(1024 * 1024):
                if not first_bytes:
                    first_bytes = chunk[:32]
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(status_code=413, detail="文件超过大小限制")
                digest.update(chunk)
                await output.write(chunk)
        filename = validate_upload(file.filename, file.content_type or "", first_bytes)
        sha256 = digest.hexdigest()
        duplicate = await session.scalar(
            select(Document).where(
                Document.knowledge_base_id == knowledge_base_id,
                Document.sha256 == sha256,
            )
        )
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="相同文件已存在")

        document = Document(
            knowledge_base_id=knowledge_base_id,
            title=(title or Path(filename).stem)[:500],
            filename=filename,
            media_type=file.content_type or "application/octet-stream",
            size_bytes=size,
            sha256=sha256,
            object_key="pending",
            status="uploaded",
            source_time=source_time,
            created_by_id=user.id,
        )
        session.add(document)
        await session.flush()
        document.object_key = _object_key(knowledge_base_id, document.id, filename)
        storage = await create_runtime_storage(session)
        await storage.put_file(
            document.object_key,
            temporary_path,
            document.media_type,
        )
        # Keep the INSERT-returned timestamp loaded until the initial job is built.
        # A second flush here emits an UPDATE with the server-side ``onupdate``
        # expression, expires ``updated_at``, and makes _new_job's synchronous
        # attribute access attempt async I/O (SQLAlchemy MissingGreenlet).
        job = _new_job(document)
        session.add(job)
        document.status = "queued"
        await session.commit()
        # The UPDATE uses a server-side onupdate expression, so SQLAlchemy expires
        # updated_at after commit. Refresh explicitly before FastAPI serializes the
        # ORM object; implicit async loading during serialization is not allowed.
        await session.refresh(document)
        process_document.send(str(job.id))
        return document
    finally:
        temporary_path.unlink(missing_ok=True)
        await file.close()


@router.post("/uploads/init", response_model=UploadInitResponse)
async def init_direct_upload(
    payload: UploadInitRequest,
    user: DocumentWriteUser,
    session: DatabaseSession,
    knowledge_base_id: uuid.UUID = Query(...),
) -> UploadInitResponse:
    await require_knowledge_base_access(session, user, knowledge_base_id, write=True)
    if payload.size_bytes > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="文件超过大小限制")
    filename = safe_filename(payload.filename)
    from synapsekb.document_processing.validation import ALLOWED_SUFFIXES

    if Path(filename).suffix.lower() not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=422, detail="不支持的文件类型")
    duplicate = await session.scalar(
        select(Document).where(
            Document.knowledge_base_id == knowledge_base_id,
            Document.sha256 == payload.sha256,
        )
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="相同文件已存在")
    document = Document(
        knowledge_base_id=knowledge_base_id,
        title=payload.title or Path(filename).stem,
        filename=filename,
        media_type=payload.media_type,
        size_bytes=payload.size_bytes,
        sha256=payload.sha256,
        object_key="pending",
        status="uploading",
        source_time=payload.source_time,
        created_by_id=user.id,
    )
    session.add(document)
    await session.flush()
    document.object_key = _object_key(knowledge_base_id, document.id, filename)
    storage = await create_runtime_storage(session)
    upload_url = await storage.presign_upload(
        document.object_key,
        payload.media_type,
        900,
    )
    if upload_url is None:
        await session.rollback()
        raise HTTPException(status_code=409, detail="本地存储请使用 /documents/upload")
    await session.commit()
    return UploadInitResponse(
        document=DocumentRead.model_validate(document),
        upload_url=upload_url,
        method="PUT",
        expires_in=900,
    )


@router.post("/uploads/complete", response_model=DocumentRead)
async def complete_direct_upload(
    payload: UploadCompleteRequest,
    user: DocumentWriteUser,
    session: DatabaseSession,
) -> Document:
    document = await session.get(Document, payload.document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    await require_knowledge_base_access(
        session,
        user,
        document.knowledge_base_id,
        write=True,
    )
    if document.status != "uploading":
        raise HTTPException(status_code=409, detail="文档不处于上传状态")
    storage = await create_runtime_storage(session)
    if not await storage.exists(document.object_key):
        raise HTTPException(status_code=409, detail="对象存储中尚未找到文件")
    actual_size = 0
    actual_digest = hashlib.sha256()
    first_bytes = b""
    async for chunk in storage.iter_bytes(document.object_key):
        if not first_bytes:
            first_bytes = chunk[:32]
        actual_size += len(chunk)
        if actual_size > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="对象超过大小限制")
        actual_digest.update(chunk)
    if actual_size != document.size_bytes or actual_digest.hexdigest() != document.sha256:
        document.status = "failed"
        document.error_summary = "对象大小或 SHA-256 与上传声明不一致"
        await session.commit()
        raise HTTPException(status_code=409, detail=document.error_summary)
    try:
        validate_upload(document.filename, document.media_type, first_bytes)
    except ValueError as exc:
        document.status = "failed"
        document.error_summary = str(exc)
        await session.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    job = _new_job(document)
    session.add(job)
    document.status = "queued"
    await session.commit()
    await session.refresh(document)
    process_document.send(str(job.id))
    return document


@router.get("/tags", response_model=list[DocumentTagRead])
async def list_document_tags(
    knowledge_base_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> list[DocumentTag]:
    await require_knowledge_base_access(session, user, knowledge_base_id)
    return list(
        (
            await session.scalars(
                select(DocumentTag)
                .where(DocumentTag.knowledge_base_id == knowledge_base_id)
                .order_by(DocumentTag.name)
            )
        ).all()
    )


@router.post("/tags", response_model=DocumentTagRead, status_code=status.HTTP_201_CREATED)
async def create_document_tag(
    payload: DocumentTagCreate,
    user: CurrentUser,
    session: DatabaseSession,
) -> DocumentTag:
    await require_knowledge_base_access(
        session,
        user,
        payload.knowledge_base_id,
        write=True,
    )
    existing = await session.scalar(
        select(DocumentTag).where(
            DocumentTag.knowledge_base_id == payload.knowledge_base_id,
            DocumentTag.name == payload.name,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="标签名称已存在")
    tag = DocumentTag(
        knowledge_base_id=payload.knowledge_base_id,
        name=payload.name,
        color=payload.color,
    )
    session.add(tag)
    await session.commit()
    return tag


@router.post("/import-url", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def import_url_document(
    payload: UrlImportRequest,
    user: CurrentUser,
    session: DatabaseSession,
) -> Document:
    await require_knowledge_base_access(
        session,
        user,
        payload.knowledge_base_id,
        write=True,
    )
    try:
        fetched = await fetch_public_document(
            str(payload.url),
            allowed_ports=settings.allowed_url_ports,
            max_bytes=min(settings.max_upload_bytes, 20 * 1024 * 1024),
        )
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"网页抓取失败: {exc}") from exc
    sha256 = hashlib.sha256(fetched.content).hexdigest()
    duplicate = await session.scalar(
        select(Document).where(
            Document.knowledge_base_id == payload.knowledge_base_id,
            Document.sha256 == sha256,
        )
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="相同网页内容已存在")
    filename = f"web-{sha256[:12]}{fetched.suffix}"
    document = Document(
        knowledge_base_id=payload.knowledge_base_id,
        title=(payload.title or fetched.final_url)[:500],
        filename=filename,
        media_type=fetched.media_type,
        size_bytes=len(fetched.content),
        sha256=sha256,
        object_key="pending",
        status="uploaded",
        source_time=payload.source_time,
        parse_config={
            "source_kind": "url",
            "requested_url": str(payload.url),
            "final_url": fetched.final_url,
        },
        created_by_id=user.id,
    )
    session.add(document)
    await session.flush()
    document.object_key = _object_key(payload.knowledge_base_id, document.id, filename)
    temporary = tempfile.NamedTemporaryFile(prefix="synapsekb-url-", delete=False)
    temporary_path = Path(temporary.name)
    try:
        temporary.write(fetched.content)
        temporary.close()
        storage = await create_runtime_storage(session)
        await storage.put_file(
            document.object_key,
            temporary_path,
            document.media_type,
        )
    finally:
        temporary.close()
        temporary_path.unlink(missing_ok=True)
    job = _new_job(document)
    session.add(job)
    document.status = "queued"
    await session.commit()
    await session.refresh(document)
    process_document.send(str(job.id))
    return document


@router.get("/{document_id}", response_model=DocumentRead)
async def get_document(
    document_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> Document:
    document = await session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    await require_knowledge_base_access(session, user, document.knowledge_base_id)
    return document


@router.patch("/{document_id}", response_model=DocumentRead)
async def update_document(
    document_id: uuid.UUID,
    payload: DocumentUpdate,
    user: CurrentUser,
    session: DatabaseSession,
) -> Document:
    document = await session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    await require_knowledge_base_access(
        session,
        user,
        document.knowledge_base_id,
        write=True,
    )
    supplied = payload.model_fields_set
    if "title" in supplied and payload.title is not None:
        document.title = payload.title
    if "source_time" in supplied:
        document.source_time = payload.source_time
        now = datetime.now(UTC)
        await session.execute(
            update(Chunk)
            .where(Chunk.document_id == document.id)
            .values(source_time=payload.source_time, updated_at=now)
        )
    if payload.tag_ids is not None:
        requested = set(payload.tag_ids)
        actual = set(
            (
                await session.scalars(
                    select(DocumentTag.id).where(
                        DocumentTag.knowledge_base_id == document.knowledge_base_id,
                        DocumentTag.id.in_(requested),
                    )
                )
            ).all()
        )
        if actual != requested:
            raise HTTPException(status_code=422, detail="包含不存在或属于其他知识库的标签")
        await session.execute(
            delete(document_tag_links).where(document_tag_links.c.document_id == document.id)
        )
        if requested:
            await session.execute(
                document_tag_links.insert(),
                [{"document_id": document.id, "tag_id": tag_id} for tag_id in requested],
            )
    document.updated_at = datetime.now(UTC)
    await session.commit()
    await schedule_wiki_update(document.knowledge_base_id, document.id)
    return document


@router.get("/{document_id}/parsed")
async def read_parsed_document(
    document_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> Response:
    document = await session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    await require_knowledge_base_access(session, user, document.knowledge_base_id)
    if document.parsed_text_key is None:
        raise HTTPException(status_code=409, detail="文档尚未完成解析")
    storage = await create_runtime_storage(session)
    return StreamingResponse(
        storage.iter_bytes(document.parsed_text_key),
        media_type="text/markdown; charset=utf-8",
    )


@router.get("/{document_id}/chunks", response_model=list[ChunkRead])
async def list_document_chunks(
    document_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[Chunk]:
    document = await session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    await require_knowledge_base_access(session, user, document.knowledge_base_id)
    return list(
        (
            await session.scalars(
                select(Chunk)
                .where(Chunk.document_id == document.id)
                .order_by(Chunk.ordinal)
                .offset(offset)
                .limit(limit)
            )
        ).all()
    )


@router.get("/{document_id}/jobs", response_model=list[ProcessingJobRead])
async def list_document_jobs(
    document_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> list[ProcessingJob]:
    document = await session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    await require_knowledge_base_access(session, user, document.knowledge_base_id)
    query = (
        select(ProcessingJob)
        .where(ProcessingJob.document_id == document_id)
        .order_by(ProcessingJob.created_at.desc())
    )
    return list((await session.scalars(query)).all())


@router.post("/{document_id}/cancel", response_model=ProcessingJobRead)
async def cancel_document_job(
    document_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> ProcessingJob:
    document = await session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    await require_knowledge_base_access(
        session,
        user,
        document.knowledge_base_id,
        write=True,
    )
    job = await session.scalar(
        select(ProcessingJob)
        .where(
            ProcessingJob.document_id == document_id,
            ProcessingJob.status.in_(["queued", "running"]),
        )
        .order_by(ProcessingJob.created_at.desc())
        .with_for_update()
    )
    if job is None:
        raise HTTPException(status_code=409, detail="没有可取消的任务")
    job.cancel_requested_at = datetime.now(UTC)
    job.stage = "cancelling"
    await session.commit()
    return job


@router.post("/{document_id}/retry", response_model=ProcessingJobRead)
async def retry_document_job(
    document_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> ProcessingJob:
    document = await session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    await require_knowledge_base_access(
        session,
        user,
        document.knowledge_base_id,
        write=True,
    )
    document.updated_at = datetime.now(UTC)
    await session.flush()
    job = _new_job(document)
    session.add(job)
    document.status = "queued"
    document.error_summary = None
    await session.commit()
    process_document.send(str(job.id))
    return job


@router.get("/{document_id}/download")
async def download_document(
    document_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> Response:
    document = await session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    await require_knowledge_base_access(session, user, document.knowledge_base_id)
    storage = await create_runtime_storage(session)
    url = await storage.presign_download(document.object_key)
    if url:
        return RedirectResponse(url, status_code=307)
    return StreamingResponse(
        storage.iter_bytes(document.object_key),
        media_type=document.media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{document.filename}"},
    )


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> Response:
    document = await session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    await require_knowledge_base_access(
        session,
        user,
        document.knowledge_base_id,
        write=True,
    )
    affected_pages = list(
        (
            await session.scalars(
                select(WikiPage)
                .join(
                    WikiPageSource,
                    WikiPageSource.page_version_id == WikiPage.current_version_id,
                )
                .where(WikiPageSource.document_id == document.id)
                .with_for_update()
            )
        ).all()
    )
    for page in affected_pages:
        remaining_sources = await session.scalar(
            select(func.count())
            .select_from(WikiPageSource)
            .where(
                WikiPageSource.page_version_id == page.current_version_id,
                WikiPageSource.document_id != document.id,
            )
        )
        if not remaining_sources:
            page.current_version_id = None
            await session.execute(delete(WikiNode).where(WikiNode.page_id == page.id))
    await session.execute(delete(WikiEdge).where(WikiEdge.source_document_id == document.id))
    await session.flush()
    connected_source = WikiEdge.source_node_id == WikiNode.id
    connected_target = WikiEdge.target_node_id == WikiNode.id
    await session.execute(
        delete(WikiNode).where(
            WikiNode.node_type == "topic",
            ~exists(select(WikiEdge.id).where(or_(connected_source, connected_target))),
        )
    )
    object_keys = {document.object_key}
    if document.parsed_text_key:
        object_keys.add(document.parsed_text_key)
    session.add(
        AuditLog(
            actor_user_id=user.id,
            action="document.delete",
            resource_type="document",
            resource_id=document.id,
            metadata_json={
                "knowledge_base_id": str(document.knowledge_base_id),
                "filename": document.filename,
            },
            created_at=datetime.now(UTC),
        )
    )
    await session.delete(document)
    await session.commit()
    storage = await create_runtime_storage(session)
    for key in object_keys:
        try:
            await storage.delete(key)
        except Exception:
            logger.exception("object_delete_failed", object_key=key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
