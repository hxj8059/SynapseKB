from __future__ import annotations

# ruff: noqa: S106 -- isolated test accounts, never real credentials
import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from alembic import command
from alembic.config import Config
from dramatiq import Message
from dramatiq.brokers.redis import RedisBroker
from fastapi import FastAPI, HTTPException, Request, Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from synapsekb.api.routes import auth, documents, users
from synapsekb.api.schemas import (
    KnowledgeBaseMembersUpdate,
    LoginRequest,
    UserApprovalDecision,
    UserCreate,
    UserUpdate,
)
from synapsekb.auth.dependencies import get_current_user
from synapsekb.auth.policy import knowledge_base_access_clause, require_knowledge_base_access
from synapsekb.config import get_settings
from synapsekb.database.models import (
    Document,
    KnowledgeBase,
    TaskDispatch,
    User,
    UserApprovalRequest,
    WikiSpace,
    WikiUpdateJob,
)
from synapsekb.database.session import get_session
from synapsekb.document_processing.url_fetcher import FetchedDocument
from synapsekb.mcp import tools as mcp_tools
from synapsekb.mcp.auth import McpPrincipal, principal_var
from synapsekb.tasks import dispatch, recovery
from synapsekb.tasks.broker import DurableMessageId
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def services():
    if os.getenv("RUN_DOCKER_TESTS") != "1":
        pytest.skip("set RUN_DOCKER_TESTS=1")
    with (
        PostgresContainer("pgvector/pgvector:0.8.0-pg16") as pg,
        RedisContainer("redis:7.4.9-alpine") as redis,
    ):
        url = pg.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        previous = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = url
        get_settings.cache_clear()
        try:
            command.upgrade(Config("alembic.ini"), "head")
        finally:
            if previous is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous
            get_settings.cache_clear()
        yield url, redis.get_client()


@pytest.fixture
async def database(services, monkeypatch):
    url, redis = services
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE task_dispatches, users CASCADE"))
    broker = RedisBroker(client=redis, namespace=f"test-dispatch-{uuid.uuid4()}")
    broker.add_middleware(DurableMessageId())
    for mod in (dispatch, recovery):
        monkeypatch.setattr(mod, "AsyncSessionFactory", factory)
        monkeypatch.setattr(mod, "broker", broker)
    monkeypatch.setattr(dispatch, "engine", engine)
    monkeypatch.setattr(mcp_tools, "AsyncSessionFactory", factory)
    yield factory, broker
    await engine.dispose()


async def seed(factory):
    async with factory() as session:
        suffix = uuid.uuid4().hex
        admin = User(
            email=f"admin-{suffix}@example.com",
            display_name="管理员",
            password_hash="unused",
            role="admin",
        )
        root = User(
            email=f"root-{suffix}@example.com",
            display_name="超级管理员",
            password_hash="unused",
            role="super_admin",
        )
        session.add_all([admin, root])
        await session.flush()
        kb = KnowledgeBase(name=f"研究库-{suffix}", created_by_id=root.id, visibility="users")
        session.add(kb)
        await session.flush()
        space = WikiSpace(knowledge_base_id=kb.id)
        session.add(space)
        await session.commit()
        return admin, root, kb, space


async def new_job(factory, space, *, outbox=True):
    async with factory() as session:
        job = WikiUpdateJob(space_id=space.id, generation_id=uuid.uuid4(), status="queued")
        session.add(job)
        row = dispatch.add_dispatch(session, "wiki_update", job) if outbox else None
        await session.commit()
        return job, row


async def test_approval_and_membership_are_enforced_in_rest_mcp_and_login(database, monkeypatch):
    factory, _ = database
    admin, root, kb, _ = await seed(factory)
    async with factory() as session:
        member = await users.create_user(
            UserCreate(
                email=f"member-{uuid.uuid4().hex}@example.com",
                display_name="研究员",
                password="initial-test-password",
            ),
            admin,
            session,
        )
        assert not member.is_active and member.approval_status == "pending"
        login_payload = LoginRequest(email=member.email, password="initial-test-password")
        login_request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1234)})
        with pytest.raises(HTTPException) as login_denied:
            await auth.login(login_payload, login_request, Response(), session)
        assert login_denied.value.status_code == 401
        approval = await session.scalar(
            select(UserApprovalRequest).where(UserApprovalRequest.user_id == member.id)
        )
        approval_id = approval.id
        with pytest.raises(HTTPException) as denied:
            await users.review_approval(
                approval.id, UserApprovalDecision(decision="approved"), admin, session
            )
        assert denied.value.status_code == 403
        with pytest.raises(HTTPException):
            await users.update_user(member.id, UserUpdate(is_active=True), admin, session)
        await session.rollback()
        await users.review_approval(
            approval_id, UserApprovalDecision(decision="approved"), root, session
        )
        await session.refresh(member)
        assert member.is_active and member.approval_status == "approved"
        logged_in = await auth.login(login_payload, login_request, Response(), session)
        assert logged_in.user.id == member.id and logged_in.access_token
        with pytest.raises(HTTPException):
            await require_knowledge_base_access(session, member, kb.id)
        await users.update_knowledge_base_permissions(
            kb.id,
            KnowledgeBaseMembersUpdate(visibility="users", member_ids=[member.id]),
            root,
            session,
        )
        assert (await require_knowledge_base_access(session, member, kb.id)).id == kb.id
        principal = principal_var.set(McpPrincipal(member.id, uuid.uuid4(), frozenset({"kb:read"})))
        try:
            assert kb.id in {uuid.UUID(item["id"]) for item in await mcp_tools.kb_list()}
            await users.update_knowledge_base_permissions(
                kb.id, KnowledgeBaseMembersUpdate(visibility="users", member_ids=[]), admin, session
            )
            assert kb.id not in {uuid.UUID(item["id"]) for item in await mcp_tools.kb_list()}
            with pytest.raises(HTTPException):
                await mcp_tools.kb_get(str(kb.id))
        finally:
            principal_var.reset(principal)
        with pytest.raises(HTTPException):
            await users.create_user(
                UserCreate(
                    email=f"bad-{uuid.uuid4().hex}@example.com",
                    display_name="越权",
                    password="initial-test-password",
                    role="super_admin",
                ),
                admin,
                session,
            )
        with pytest.raises(HTTPException):
            await users.update_user(
                root.id, UserUpdate(password="changed-test-password"), admin, session
            )
        visible = set(
            (
                await session.scalars(
                    select(KnowledgeBase.id).where(knowledge_base_access_clause(member))
                )
            ).all()
        )
        assert kb.id not in visible


async def test_document_filters_apply_identically_to_rows_and_total(database):
    factory, _ = database
    _, root, kb, _ = await seed(factory)
    async with factory() as session:
        for n, source, created in [
            (1, "2024-01-01", "2026-08-01"),
            (2, "2025-01-01", "2026-08-01"),
            (3, None, "2026-08-02"),
            (4, "2024-01-01", "2025-08-01"),
        ]:
            session.add(
                Document(
                    knowledge_base_id=kb.id,
                    title=f"Report {n}",
                    filename=f"{n}.txt",
                    media_type="text/plain",
                    size_bytes=2,
                    sha256=f"{n:064}",
                    object_key=f"test/{uuid.uuid4()}",
                    status="ready",
                    created_by_id=root.id,
                    source_time=datetime.fromisoformat(source).replace(tzinfo=UTC)
                    if source
                    else None,
                    created_at=datetime.fromisoformat(created).replace(tzinfo=UTC),
                )
            )
        await session.commit()
    app = FastAPI()
    app.include_router(documents.router, prefix="/documents")

    async def session_dep():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = session_dep
    app.dependency_overrides[get_current_user] = lambda: root
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        params = {
            "knowledge_base_id": str(kb.id),
            "source_from": "2024-01-01T00:00:00Z",
            "source_to": "2024-12-31T23:59:59Z",
            "created_from": "2026-01-01T00:00:00Z",
        }
        response = await client.get("/documents", params=params)
        assert response.status_code == 200, response.text
        assert [item["title"] for item in response.json()] == ["Report 1"]
        assert (await client.get("/documents/count", params=params)).json()["count"] == 1
        params["include_unknown"] = "true"
        assert (await client.get("/documents/count", params=params)).json()["count"] == 2
        params["source_to"] = "2023-01-01T00:00:00Z"
        assert (await client.get("/documents/count", params=params)).status_code == 422


async def test_outbox_handles_queued_age_prefetch_and_send_commit_gap(database):
    factory, broker = database
    _, _, _, space = await seed(factory)
    job, row = await new_job(factory, space)
    assert await dispatch.publish_pending(dispatch_id=row.id) == 1
    assert broker.client.llen(f"{broker.namespace}:wiki") == 1
    async with factory() as session:
        stored = await session.get(TaskDispatch, row.id)
        assert stored.redis_message_id == row.redis_message_id
        stored.status = "pending"  # Simulate SQL commit lost after successful send.
        await session.commit()
    assert await dispatch.publish_pending(dispatch_id=row.id) == 1
    assert broker.client.llen(f"{broker.namespace}:wiki") == 1
    async with factory() as session:
        queued = await session.get(WikiUpdateJob, job.id)
        queued.updated_at = datetime.now(UTC) - timedelta(days=7)
        await session.commit()
    for _ in range(3):
        assert (await dispatch.reconcile_dispatches())["missing"] == 0
    # A fetched message disappears from the list, but remains in .msgs until ack.
    broker.client.lpop(f"{broker.namespace}:wiki")
    assert (await dispatch.reconcile_dispatches())["missing"] == 0
    broker.client.hdel(f"{broker.namespace}:wiki.msgs", row.redis_message_id)
    assert (await dispatch.reconcile_dispatches())["missing"] == 1
    assert await dispatch.publish_pending(dispatch_id=row.id) == 1


async def test_duplicate_deliveries_claim_once_and_stale_heartbeat_keeps_live_worker(
    database, monkeypatch
):
    factory, broker = database
    _, _, _, space = await seed(factory)
    job, row = await new_job(factory, space)
    await dispatch.publish_pending(dispatch_id=row.id)
    raw = broker.client.hget(f"{broker.namespace}:wiki.msgs", row.redis_message_id)
    message = Message.decode(raw)
    monkeypatch.setattr(dispatch.CurrentMessage, "get_current_message", lambda: message)
    started, finish = asyncio.Event(), asyncio.Event()
    calls = 0

    async def work():
        nonlocal calls
        calls += 1
        started.set()
        await finish.wait()

    first = asyncio.create_task(dispatch.run_dispatched("wiki_update", job.id, work))
    await asyncio.wait_for(started.wait(), 5)
    await dispatch.run_dispatched("wiki_update", job.id, work)
    async with factory() as session:
        current = await session.get(TaskDispatch, row.id)
        current.heartbeat_at = datetime.now(UTC) - timedelta(hours=1)
        await session.commit()
    assert (await dispatch.reconcile_dispatches())["stale"] == 0
    finish.set()
    await first
    await dispatch.run_dispatched("wiki_update", job.id, work)
    assert calls == 1


async def test_legacy_queue_dedup_preserves_jobs_and_backfills_missing_only(database):
    factory, broker = database
    _, _, _, space = await seed(factory)
    job, _ = await new_job(factory, space, outbox=False)
    missing, _ = await new_job(factory, space, outbox=False)
    broker.declare_queue("wiki")
    for _ in range(3):
        broker.enqueue(
            Message(
                queue_name="wiki",
                actor_name="generate_wiki",
                args=(str(job.id),),
                kwargs={},
                options={},
            )
        )
    result = recovery.deduplicate_messages(apply=False)
    assert result["queued_duplicates"] == 2 and result["removed"] == 0
    result = recovery.deduplicate_messages(apply=True)
    assert result["removed"] == 2
    assert broker.client.hlen(result["backup_key"]) == 2
    assert await recovery.backfill_dispatches(apply=True) >= 2
    async with factory() as session:
        rows = (
            await session.scalars(
                select(TaskDispatch).where(TaskDispatch.task_id.in_([job.id, missing.id]))
            )
        ).all()
        assert {r.task_id: r.status for r in rows} == {job.id: "sent", missing.id: "pending"}
    await dispatch.publish_pending()
    assert broker.client.llen(f"{broker.namespace}:wiki") == 2
    assert recovery.deduplicate_messages(apply=True)["removed"] == 0


async def test_redis_outage_keeps_committed_pending_work(database, monkeypatch):
    factory, _ = database
    _, _, _, space = await seed(factory)
    _, row = await new_job(factory, space)
    monkeypatch.setattr(dispatch, "broker_has_message", AsyncMock(side_effect=ConnectionError()))
    assert await dispatch.publish_pending(dispatch_id=row.id) == 0
    async with factory() as session:
        stored = await session.get(TaskDispatch, row.id)
        assert stored.status == "pending"
        assert stored.error_summary == "投递失败：ConnectionError"


async def test_mcp_url_import_requires_write_scope_and_commits_document_with_dispatch(
    database, monkeypatch
):
    factory, _ = database
    _, root, kb, _ = await seed(factory)
    publisher_time = datetime(2026, 9, 1, tzinfo=UTC)
    fetched = FetchedDocument(
        content=b'<html><div id="js_content">public article</div></html>',
        media_type="text/html",
        suffix=".html",
        final_url="https://mp.weixin.qq.com/s/test",
        title="公开文章",
        source_time=publisher_time,
    )
    fetch = AsyncMock(return_value=fetched)
    storage = AsyncMock()
    monkeypatch.setattr(documents, "fetch_public_document", fetch)
    monkeypatch.setattr(documents, "create_runtime_storage", AsyncMock(return_value=storage))
    principal = principal_var.set(McpPrincipal(root.id, uuid.uuid4(), frozenset({"document:read"})))
    try:
        with pytest.raises(PermissionError, match="Scope"):
            await mcp_tools.document_import_url(str(kb.id), fetched.final_url)
        fetch.assert_not_awaited()
    finally:
        principal_var.reset(principal)
    principal = principal_var.set(
        McpPrincipal(root.id, uuid.uuid4(), frozenset({"document:write"}))
    )
    try:
        result = await mcp_tools.document_import_url(str(kb.id), fetched.final_url)
    finally:
        principal_var.reset(principal)
    async with factory() as session:
        document = await session.get(Document, uuid.UUID(result["id"]))
        assert document.title == "公开文章" and document.source_time == publisher_time
        outbox = (await session.scalars(select(TaskDispatch))).one()
        assert outbox.task_type == "document" and outbox.status == "sent"
    storage.put_file.assert_awaited_once()


async def test_cancelled_and_legacy_failed_work_never_executes(database, monkeypatch):
    factory, broker = database
    _, _, _, space = await seed(factory)
    job, row = await new_job(factory, space)
    await dispatch.publish_pending(dispatch_id=row.id)
    message = Message.decode(
        broker.client.hget(f"{broker.namespace}:wiki.msgs", row.redis_message_id)
    )
    monkeypatch.setattr(dispatch.CurrentMessage, "get_current_message", lambda: message)
    async with factory() as session:
        stored = await session.get(WikiUpdateJob, job.id)
        stored.cancel_requested_at = datetime.now(UTC)
        await session.commit()
    work = AsyncMock()
    await dispatch.run_dispatched("wiki_update", job.id, work)
    work.assert_not_awaited()
    async with factory() as session:
        assert (await session.get(WikiUpdateJob, job.id)).status == "cancelled"
        assert (await session.get(TaskDispatch, row.id)).status == "finished"
        failed, _ = await new_job(factory, space, outbox=False)
        failed_row = await session.get(WikiUpdateJob, failed.id)
        failed_row.status = "failed"
        await session.commit()
    monkeypatch.setattr(dispatch.CurrentMessage, "get_current_message", lambda: None)
    await dispatch.run_dispatched("wiki_update", failed.id, work)
    work.assert_not_awaited()


async def test_abandoned_claim_recovers_once_and_rollback_never_dispatches(database, monkeypatch):
    factory, _ = database
    _, _, _, space = await seed(factory)
    _, row = await new_job(factory, space)
    async with factory() as session:
        current = await session.get(TaskDispatch, row.id)
        current.status = "claimed"
        current.heartbeat_at = datetime.now(UTC) - timedelta(hours=1)
        await session.commit()
    assert (await dispatch.reconcile_dispatches())["stale"] == 1
    assert (await dispatch.reconcile_dispatches())["stale"] == 0
    async with factory() as session:
        abandoned = WikiUpdateJob(space_id=space.id, generation_id=uuid.uuid4(), status="queued")
        session.add(abandoned)
        pending = dispatch.add_dispatch(session, "wiki_update", abandoned)
        pending_id = pending.id
        await session.flush()
        await session.rollback()
    assert await dispatch.publish_pending(dispatch_id=pending_id) == 0


async def test_execution_failure_retries_with_new_delivery_and_rejects_old_message(
    database, monkeypatch
):
    factory, broker = database
    _, _, _, space = await seed(factory)
    job, row = await new_job(factory, space)
    # Use the same real wiki job table with a one-retry policy to exercise the dispatcher.
    monkeypatch.setitem(dispatch.TASKS, "wiki_update", ("wiki", "generate_wiki", WikiUpdateJob, 1))
    await dispatch.publish_pending(dispatch_id=row.id)
    message = Message.decode(
        broker.client.hget(f"{broker.namespace}:wiki.msgs", row.redis_message_id)
    )
    monkeypatch.setattr(dispatch.CurrentMessage, "get_current_message", lambda: message)
    work = AsyncMock(side_effect=RuntimeError("simulated"))
    notification = AsyncMock()
    await dispatch.run_dispatched("wiki_update", job.id, work, on_error=notification)
    assert notification.await_args.args[1:] == (True, 1)
    async with factory() as session:
        current = await session.get(TaskDispatch, row.id)
        assert current.status == "pending" and current.attempts == 1
        assert current.redis_message_id != row.redis_message_id
        current.available_at = datetime.now(UTC) - timedelta(seconds=1)
        next_id = current.redis_message_id
        await session.commit()
    await dispatch.run_dispatched("wiki_update", job.id, work, on_error=notification)
    assert work.await_count == 1  # outdated duplicate is acknowledged without executing
    await dispatch.publish_pending(dispatch_id=row.id)
    next_message = Message.decode(broker.client.hget(f"{broker.namespace}:wiki.msgs", next_id))
    monkeypatch.setattr(dispatch.CurrentMessage, "get_current_message", lambda: next_message)
    await dispatch.run_dispatched("wiki_update", job.id, work, on_error=notification)
    assert notification.await_args.args[1:] == (False, 2)
    async with factory() as session:
        assert (await session.get(TaskDispatch, row.id)).status == "failed"
        assert (await session.get(WikiUpdateJob, job.id)).status == "failed"
