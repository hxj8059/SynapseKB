import asyncio
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, true
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from synapsekb.config import get_settings
from synapsekb.database.models import (
    KnowledgeBase,
    ProviderModel,
    User,
    WikiNode,
    WikiPage,
    WikiPageVersion,
    WikiSpace,
)
from synapsekb.models.provider import DeterministicMockProvider
from synapsekb.wiki.index import query_wiki_index
from synapsekb.wiki.search import hybrid_wiki_search
from testcontainers.postgres import PostgresContainer


async def _exercise_wiki_index(database_url: str) -> None:
    engine = create_async_engine(database_url)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        user = User(
            email="wiki-index@example.test",
            display_name="Wiki Index",
            password_hash=os.urandom(16).hex(),
            role="admin",
        )
        session.add(user)
        await session.flush()
        knowledge_base = KnowledgeBase(
            name="Wiki index test",
            created_by_id=user.id,
            wiki_node_types=["产品", "个股"],
        )
        session.add(knowledge_base)
        await session.flush()
        space = WikiSpace(knowledge_base_id=knowledge_base.id, published_version=3)
        session.add(space)
        await session.flush()

        definitions = [
            ("胜宏科技", "个股", False),
            ("沪电科技", "个股", False),
            ("PCB", "产品", False),
            ("旧页面", "产品", True),
        ]
        for sort_order, (title, node_type, archived) in enumerate(definitions):
            page = WikiPage(
                space_id=space.id,
                slug=f"page-{sort_order}",
                title=title,
                summary=f"{title} summary",
                sort_order=sort_order,
                is_archived=archived,
            )
            session.add(page)
            await session.flush()
            version = WikiPageVersion(
                page_id=page.id,
                version_number=1,
                content=f"# {title}",
            )
            session.add(version)
            await session.flush()
            page.current_version_id = version.id
            session.add(
                WikiNode(
                    space_id=space.id,
                    node_type=node_type,
                    label=title,
                    page_id=page.id,
                    source_page_id=page.id,
                )
            )
        await session.commit()

        first_page = await query_wiki_index(
            session,
            space,
            time_clause=true(),
            limit=1,
            offset=0,
            query="科技",
        )
        assert first_page.total == 2
        assert first_page.total_published == 3
        assert len(first_page.items) == 1
        assert first_page.published_version == 3
        assert [(item.type, item.count) for item in first_page.type_counts] == [
            ("个股", 2),
            ("产品", 1),
        ]

        second_page = await query_wiki_index(
            session,
            space,
            time_clause=true(),
            limit=1,
            offset=1,
            query="科技",
        )
        assert second_page.items[0].title == "沪电科技"

        products = await query_wiki_index(
            session,
            space,
            time_clause=true(),
            limit=30,
            offset=0,
            node_type="产品",
        )
        assert products.total == 1
        assert products.items[0].title == "PCB"

        literal_wildcard = await query_wiki_index(
            session,
            space,
            time_clause=true(),
            limit=30,
            offset=0,
            query="%",
        )
        assert literal_wildcard.total == 0

        keyword_fallback = await hybrid_wiki_search(
            session,
            knowledge_base=knowledge_base,
            space=space,
            query="PCB",
            time_clause=true(),
            limit=5,
        )
        assert keyword_fallback.retrieval_mode == "keyword_fallback"
        assert keyword_fallback.items[0].title == "PCB"
        assert keyword_fallback.items[0].keyword_score == 1.0

        embedding_model = ProviderModel(
            name="Wiki search mock embedding",
            kind="embedding",
            provider="mock",
            base_url="http://mock.invalid/v1",
            model_name="mock-embedding",
            embedding_dimensions=8,
        )
        session.add(embedding_model)
        await session.flush()
        knowledge_base.embedding_model_id = embedding_model.id
        knowledge_base.embedding_dimensions = 8
        pcb_node = await session.scalar(
            select(WikiNode).where(
                WikiNode.space_id == space.id,
                WikiNode.label == "PCB",
            )
        )
        assert pcb_node is not None
        semantic_query = "高速互连板材的需求与供应链"
        provider = DeterministicMockProvider(8)
        pcb_node.embedding = (await provider.embeddings([semantic_query]))[0]
        pcb_node.embedding_model_id = embedding_model.id
        await session.commit()

        semantic_result = await hybrid_wiki_search(
            session,
            knowledge_base=knowledge_base,
            space=space,
            query=semantic_query,
            time_clause=true(),
            limit=5,
        )
        assert semantic_result.retrieval_mode == "hybrid"
        assert semantic_result.items[0].title == "PCB"
        assert semantic_result.items[0].semantic_score == 1.0
    await engine.dispose()


@pytest.mark.integration
def test_wiki_index_is_filtered_paginated_and_excludes_archived_pages() -> None:
    if os.getenv("RUN_DOCKER_TESTS") != "1":
        pytest.skip("set RUN_DOCKER_TESTS=1 to run Docker integration tests")
    with PostgresContainer("pgvector/pgvector:0.8.0-pg16") as postgres:
        url = postgres.get_connection_url().replace(
            "postgresql+psycopg2",
            "postgresql+asyncpg",
        )
        previous = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = url
        get_settings.cache_clear()
        try:
            command.upgrade(Config("alembic.ini"), "head")
            asyncio.run(_exercise_wiki_index(url))
        finally:
            if previous is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous
            get_settings.cache_clear()
