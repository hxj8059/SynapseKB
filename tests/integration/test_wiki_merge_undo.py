import asyncio
import os
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from synapsekb.config import get_settings
from synapsekb.database.models import (
    KnowledgeBase,
    User,
    WikiEdge,
    WikiEntityResolution,
    WikiNode,
    WikiPage,
    WikiPageVersion,
    WikiSpace,
)
from synapsekb.wiki.entity_resolution import add_node_alias
from synapsekb.wiki.health import merge_wiki_pages, undo_wiki_page_merge
from testcontainers.postgres import PostgresContainer


async def _exercise_merge_undo(database_url: str) -> None:
    engine = create_async_engine(database_url)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        user = User(
            email="admin@example.test",
            display_name="Admin",
            password_hash=os.urandom(16).hex(),
            role="admin",
        )
        session.add(user)
        await session.flush()
        knowledge_base = KnowledgeBase(
            name="Merge test",
            created_by_id=user.id,
            wiki_node_types=["产品"],
        )
        session.add(knowledge_base)
        await session.flush()
        space = WikiSpace(knowledge_base_id=knowledge_base.id, published_version=1)
        session.add(space)
        await session.flush()
        target = WikiPage(
            space_id=space.id,
            slug="target",
            title="高容量 MLCC",
            summary="目标摘要",
        )
        source = WikiPage(
            space_id=space.id,
            slug="source",
            title="高容 MLCC",
            summary="来源摘要",
        )
        session.add_all([target, source])
        await session.flush()
        target_version = WikiPageVersion(
            page_id=target.id,
            version_number=1,
            content="# 高容量 MLCC\n\n目标事实。[1]",
            source_time=datetime(2026, 1, 1, tzinfo=UTC),
        )
        source_version = WikiPageVersion(
            page_id=source.id,
            version_number=1,
            content="# 高容 MLCC\n\n来源事实。[2]",
            source_time=datetime(2026, 2, 1, tzinfo=UTC),
        )
        session.add_all([target_version, source_version])
        await session.flush()
        target.current_version_id = target_version.id
        source.current_version_id = source_version.id
        target_node = WikiNode(
            space_id=space.id,
            node_type="产品",
            label=target.title,
            page_id=target.id,
            source_page_id=target.id,
        )
        source_node = WikiNode(
            space_id=space.id,
            node_type="产品",
            label=source.title,
            page_id=source.id,
            source_page_id=source.id,
        )
        session.add_all([target_node, source_node])
        await session.flush()
        await add_node_alias(
            session,
            node=source_node,
            alias="高容 MLCC",
            source="canonical",
        )
        original_edge = WikiEdge(
            space_id=space.id,
            source_node_id=source_node.id,
            target_node_id=target_node.id,
            edge_type="related_to",
            evidence="原始关系",
            source_page_id=source.id,
        )
        session.add(original_edge)
        await session.commit()

        merged = await merge_wiki_pages(
            session,
            space=space,
            target_page_id=target.id,
            source_page_ids=[source.id],
            change_summary="integration test merge",
            actor_user_id=user.id,
        )
        resolution = await session.scalar(
            select(WikiEntityResolution).where(
                WikiEntityResolution.space_id == space.id,
                WikiEntityResolution.decision == "merge",
            )
        )
        assert resolution is not None
        assert resolution.snapshot_json["merged_version_id"] == str(merged.current_version_id)
        assert (await session.get(WikiPage, source.id)).is_archived is True  # type: ignore[union-attr]
        assert await session.get(WikiNode, source_node.id) is None

        restored = await undo_wiki_page_merge(
            session,
            space=space,
            resolution_id=resolution.id,
            actor_user_id=user.id,
        )
        restored_source = await session.get(WikiPage, source.id)
        restored_node = await session.get(WikiNode, source_node.id)
        restored_edge = await session.get(WikiEdge, original_edge.id)
        assert restored.current_version_id == target_version.id
        assert restored_source is not None and restored_source.is_archived is False
        assert restored_source.merged_into_page_id is None
        assert restored_node is not None and restored_node.page_id == source.id
        assert restored_edge is not None
        assert restored_edge.source_node_id == source_node.id
        assert restored_edge.target_node_id == target_node.id
        assert resolution.decision == "reverted"
        assert resolution.reverted_at is not None

        automatic_merge = await merge_wiki_pages(
            session,
            space=space,
            target_page_id=target.id,
            source_page_ids=[source.id],
            change_summary="LLM automatic identity merge",
            actor_user_id=None,
            decision_source="llm_auto",
        )
        await session.refresh(resolution)
        assert resolution.decision == "merge"
        assert resolution.decision_source == "llm_auto"
        assert resolution.decided_by_user_id is None
        assert automatic_merge.current_version_id != target_version.id

        await undo_wiki_page_merge(
            session,
            space=space,
            resolution_id=resolution.id,
            actor_user_id=user.id,
        )
        await session.refresh(resolution)
        assert resolution.decision == "reverted"
    await engine.dispose()


@pytest.mark.integration
def test_wiki_merge_can_restore_pages_nodes_aliases_and_edges() -> None:
    if os.getenv("RUN_DOCKER_TESTS") != "1":
        pytest.skip("set RUN_DOCKER_TESTS=1 to run Docker integration tests")
    with PostgresContainer("pgvector/pgvector:0.8.0-pg16") as postgres:
        url = postgres.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        previous = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = url
        get_settings.cache_clear()
        try:
            command.upgrade(Config("alembic.ini"), "head")
            asyncio.run(_exercise_merge_undo(url))
        finally:
            if previous is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous
            get_settings.cache_clear()
