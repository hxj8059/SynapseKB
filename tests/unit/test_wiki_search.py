import uuid

import pytest
from sqlalchemy import true
from synapsekb.database.models import KnowledgeBase, WikiNode, WikiPage, WikiSpace
from synapsekb.wiki import search


def _page_node(title: str) -> tuple[WikiPage, WikiNode]:
    page = WikiPage(
        id=uuid.uuid4(),
        space_id=uuid.uuid4(),
        slug=title.casefold(),
        title=title,
        summary=f"{title} 摘要",
        current_version_id=uuid.uuid4(),
    )
    node = WikiNode(
        id=uuid.uuid4(),
        space_id=page.space_id,
        node_type="产业主题",
        label=title,
        page_id=page.id,
        source_page_id=page.id,
    )
    return page, node


async def test_hybrid_wiki_search_falls_back_to_ranked_keywords(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page, node = _page_node("数据中心液冷")

    async def keyword_candidates(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
        del args, kwargs
        return [(page, node, 0.99, "alias_exact")]

    async def semantic_candidates(*args: object, **kwargs: object) -> tuple[list[object], str]:
        del args, kwargs
        return [], "TimeoutError: embedding timeout"

    monkeypatch.setattr(search, "_keyword_candidates", keyword_candidates)
    monkeypatch.setattr(search, "_semantic_candidates", semantic_candidates)
    result = await search.hybrid_wiki_search(
        object(),  # type: ignore[arg-type]
        knowledge_base=KnowledgeBase(id=uuid.uuid4(), name="KB", created_by_id=uuid.uuid4()),
        space=WikiSpace(id=page.space_id, knowledge_base_id=uuid.uuid4()),
        query="液冷系统",
        time_clause=true(),
        limit=8,
    )

    assert result.retrieval_mode == "keyword_fallback"
    assert result.embedding_error == "TimeoutError: embedding timeout"
    assert result.items[0].page_id == page.id
    assert result.items[0].matched_by == ("alias_exact",)
    assert result.items[0].relevance_score >= 0.99


async def test_hybrid_wiki_search_fuses_semantic_and_keyword_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    semantic_page, semantic_node = _page_node("CPO 光模块")
    keyword_page, keyword_node = _page_node("CPO 行业")

    async def keyword_candidates(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
        del args, kwargs
        return [
            (keyword_page, keyword_node, 0.88, "title"),
            (semantic_page, semantic_node, 0.65, "summary"),
        ]

    async def semantic_candidates(
        *args: object,
        **kwargs: object,
    ) -> tuple[list[tuple[object, ...]], None]:
        del args, kwargs
        return [
            (semantic_page, semantic_node, 0.96),
            (keyword_page, keyword_node, 0.55),
        ], None

    monkeypatch.setattr(search, "_keyword_candidates", keyword_candidates)
    monkeypatch.setattr(search, "_semantic_candidates", semantic_candidates)
    result = await search.hybrid_wiki_search(
        object(),  # type: ignore[arg-type]
        knowledge_base=KnowledgeBase(id=uuid.uuid4(), name="KB", created_by_id=uuid.uuid4()),
        space=WikiSpace(id=semantic_page.space_id, knowledge_base_id=uuid.uuid4()),
        query="CPO 产业链",
        time_clause=true(),
        limit=8,
    )

    assert result.retrieval_mode == "hybrid"
    assert [item.page_id for item in result.items] == [semantic_page.id, keyword_page.id]
    assert result.items[0].matched_by == ("summary", "vector")
    assert result.items[0].semantic_score == 0.96
