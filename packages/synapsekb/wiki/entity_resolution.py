from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from synapsekb.database.models import (
    Chunk,
    Document,
    KnowledgeBase,
    ProviderModel,
    WikiNode,
    WikiNodeAlias,
    WikiPage,
)
from synapsekb.models.provider import create_provider

logger = structlog.get_logger()

_LABEL_SEPARATORS = re.compile(r"[^0-9a-z\u4e00-\u9fff]+", re.IGNORECASE)
_PARENTHETICAL_ALIAS = re.compile(r"[（(]([^（）()]{2,80})[）)]")
_ORGANIZATION_SUFFIX = re.compile(r"(?:股份有限公司|有限责任公司|有限公司)$")
_ORGANIZATION_NODE_TYPES = frozenset({"个股", "公司", "企业", "组织"})
_TOPIC_NODE_TYPES = frozenset({"主题", "产业主题", "行业", "产品", "概念", "技术", "材料", "工艺"})
_ASCII_ACRONYM = re.compile(r"[A-Za-z][A-Za-z0-9+.-]{1,}")
_HAN_CHARACTER = re.compile(r"[\u3400-\u9fff]")
_TOPIC_SCOPE_SUFFIX = re.compile(r"(?:行业|赛道|市场|产业链|板块|概念)$")
_TOPIC_ROLE_SUFFIX = re.compile(r"(?:厂商|供应商|生产商)$")
_TOPIC_BENEFICIARY_SUFFIX = re.compile(r"(?:涨价|降价|扩产|国产替代|需求增长|价格上涨)?受益标的$")
_TOPIC_STATE_SUFFIX = re.compile(
    r"(?:行业)?(?:产能扩张|产能增长|供需格局|供需变化|价格趋势|"
    r"景气周期|上行周期|周期|热潮|景气提升|市场空间|竞争格局|投资机会|红利期)$"
)


def normalize_wiki_label(value: str) -> str:
    """Normalize an entity label for exact identity checks, not fuzzy merging."""

    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return _LABEL_SEPARATORS.sub("", normalized)


def is_topic_node_type(node_type: str | None) -> bool:
    return bool(node_type and node_type in _TOPIC_NODE_TYPES)


def canonicalize_wiki_entity_title(value: str, *, node_type: str | None = None) -> str:
    """Collapse report-heading qualifiers into a reusable topic entity title.

    This deliberately handles only suffixes that describe a view, market scope,
    state or stock screen. Product qualifiers such as ``AI 芯片`` remain intact.
    """

    original = value.strip()
    if not original or not is_topic_node_type(node_type):
        return original
    canonical = original
    for _ in range(3):
        previous = canonical
        canonical = _TOPIC_BENEFICIARY_SUFFIX.sub("", canonical).strip(" -—_:：/")
        canonical = _TOPIC_STATE_SUFFIX.sub("", canonical).strip(" -—_:：/")
        canonical = _TOPIC_ROLE_SUFFIX.sub("", canonical).strip(" -—_:：/")
        canonical = _TOPIC_SCOPE_SUFFIX.sub("", canonical).strip(" -—_:：/")
        if canonical == previous:
            break
    return canonical or original


def wiki_label_aliases(value: str, *, node_type: str | None = None) -> list[str]:
    aliases = [value.strip()]
    canonical = canonicalize_wiki_entity_title(value, node_type=node_type)
    if canonical and canonical not in aliases:
        aliases.append(canonical)
    for candidate in list(aliases):
        without_parenthetical = _PARENTHETICAL_ALIAS.sub("", candidate).strip()
        parenthetical_values = [
            match.strip() for match in _PARENTHETICAL_ALIAS.findall(candidate) if match.strip()
        ]
        safe_parenthetical_alias = any(
            (
                bool(_ASCII_ACRONYM.fullmatch(without_parenthetical))
                or bool(_ASCII_ACRONYM.fullmatch(parenthetical))
                or bool(_HAN_CHARACTER.search(without_parenthetical))
                != bool(_HAN_CHARACTER.search(parenthetical))
            )
            for parenthetical in parenthetical_values
        )
        if safe_parenthetical_alias:
            if without_parenthetical:
                aliases.append(without_parenthetical)
            aliases.extend(parenthetical_values)
    if node_type in _ORGANIZATION_NODE_TYPES:
        # Legal-form suffixes do not change company identity. Keep brand words
        # such as “科技” and stock abbreviations such as “沪电股份” intact.
        aliases.extend(
            stripped
            for alias in list(aliases)
            if (stripped := _ORGANIZATION_SUFFIX.sub("", alias).strip()) != alias and stripped
        )
    return list(dict.fromkeys(alias for alias in aliases if alias))


async def add_node_alias(
    session: AsyncSession,
    *,
    node: WikiNode,
    alias: str,
    source: str,
) -> None:
    normalized = normalize_wiki_label(alias)
    if not normalized:
        return
    statement = (
        insert(WikiNodeAlias)
        .values(
            space_id=node.space_id,
            node_id=node.id,
            alias=alias.strip(),
            normalized_alias=normalized,
            source=source[:32],
        )
        .on_conflict_do_nothing(index_elements=["space_id", "node_id", "normalized_alias"])
    )
    await session.execute(statement)


async def ensure_canonical_node_aliases(
    session: AsyncSession,
    nodes: list[WikiNode],
) -> None:
    for node in nodes:
        if node.page_id is not None:
            aliases = wiki_label_aliases(node.label, node_type=node.node_type)
            normalized_aliases = [normalize_wiki_label(alias) for alias in aliases]
            await session.execute(
                delete(WikiNodeAlias).where(
                    WikiNodeAlias.node_id == node.id,
                    WikiNodeAlias.source == "canonical",
                    WikiNodeAlias.normalized_alias.not_in(normalized_aliases),
                )
            )
            for alias in aliases:
                await add_node_alias(
                    session,
                    node=node,
                    alias=alias,
                    source="canonical",
                )


async def ensure_page_node_embeddings(
    session: AsyncSession,
    knowledge_base: KnowledgeBase,
    pages: list[WikiPage],
    page_nodes: dict[uuid.UUID, WikiNode],
) -> tuple[int, str | None]:
    """Fill only missing/stale page vectors and return the number updated."""

    if knowledge_base.embedding_model_id is None:
        return 0, "知识库未配置 Embedding 模型，跳过语义候选召回"
    model = await session.get(ProviderModel, knowledge_base.embedding_model_id)
    if model is None or model.kind != "embedding" or not model.is_enabled:
        return 0, "知识库 Embedding 模型不存在或已停用"
    if model.embedding_dimensions not in {None, 1536}:
        return 0, "Wiki 节点向量索引固定为 1536 维，当前 Embedding 模型维度不兼容"
    pending_pages = [
        page
        for page in pages
        if page.id in page_nodes
        and (
            page_nodes[page.id].embedding is None
            or page_nodes[page.id].embedding_model_id != model.id
        )
    ]
    if not pending_pages:
        return 0, None
    provider = create_provider(model)
    try:
        vectors = await provider.embeddings(
            [f"{page.title}\n{page.summary[:800]}" for page in pending_pages]
        )
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}"[:500]
    finally:
        await provider.close()
    if any(len(vector) != 1536 for vector in vectors):
        return 0, "Embedding API 返回维度不是 1536，未写入 Wiki 节点"
    for page, vector in zip(pending_pages, vectors, strict=True):
        page_nodes[page.id].embedding = vector
        page_nodes[page.id].embedding_model_id = model.id
    await session.flush()
    return len(pending_pages), None


@dataclass(frozen=True, slots=True)
class HistoricalWikiNode:
    page_id: uuid.UUID
    node_type: str
    title: str
    summary: str
    slug: str
    aliases: tuple[str, ...]
    relevance: float

    def prompt_payload(self) -> dict[str, object]:
        return {
            "page_id": str(self.page_id),
            "type": self.node_type,
            "title": self.title,
            "aliases": list(self.aliases[:5]),
            "summary": self.summary[:160],
        }


class WikiHistoryResolver:
    """Bounded historical-node retrieval for incremental Wiki generation.

    A document receives only a small ANN/lexical shortlist. The full Wiki catalog
    is never copied into a model prompt.
    """

    def __init__(
        self,
        session: AsyncSession,
        space_id: uuid.UUID,
        embedding_model: ProviderModel | None,
    ) -> None:
        self.session = session
        self.space_id = space_id
        self.embedding_model = embedding_model
        self.provider = create_provider(embedding_model) if embedding_model is not None else None

    @classmethod
    async def create(
        cls,
        session: AsyncSession,
        knowledge_base: KnowledgeBase,
        space_id: uuid.UUID,
    ) -> WikiHistoryResolver:
        model = (
            await session.get(ProviderModel, knowledge_base.embedding_model_id)
            if knowledge_base.embedding_model_id
            else None
        )
        if (
            model is None
            or model.kind != "embedding"
            or not model.is_enabled
            or model.embedding_dimensions not in {None, 1536}
        ):
            model = None
        return cls(session, space_id, model)

    async def close(self) -> None:
        if self.provider is not None:
            await self.provider.close()

    async def retrieve(
        self,
        document: Document,
        chunks: list[Chunk],
        *,
        limit: int = 8,
    ) -> list[HistoricalWikiNode]:
        if limit <= 0:
            return []
        scores: dict[uuid.UUID, float] = {}
        query_text = "\n".join([document.title, *(chunk.content[:260] for chunk in chunks[:4])])[
            :1800
        ]

        lexical_score = func.similarity(WikiNode.label, document.title)
        lexical_rows = (
            await self.session.execute(
                select(WikiNode.page_id, lexical_score.label("score"))
                .join(WikiPage, WikiPage.id == WikiNode.page_id)
                .where(
                    WikiNode.space_id == self.space_id,
                    WikiNode.page_id.is_not(None),
                    WikiPage.is_archived.is_(False),
                    WikiPage.current_version_id.is_not(None),
                    lexical_score >= 0.25,
                )
                .order_by(lexical_score.desc())
                .limit(limit)
            )
        ).all()
        for page_id, score in lexical_rows:
            if page_id is not None:
                scores[page_id] = max(scores.get(page_id, 0), float(score))

        if self.provider is not None and self.embedding_model is not None:
            embedding_model_id = self.embedding_model.id
            try:
                vectors = await self.provider.embeddings([query_text])
                if vectors and len(vectors[0]) == 1536:
                    distance = WikiNode.embedding.cosine_distance(vectors[0])
                    semantic_rows = (
                        await self.session.execute(
                            select(WikiNode.page_id, distance.label("distance"))
                            .join(WikiPage, WikiPage.id == WikiNode.page_id)
                            .where(
                                WikiNode.space_id == self.space_id,
                                WikiNode.page_id.is_not(None),
                                WikiNode.embedding.is_not(None),
                                WikiNode.embedding_model_id == embedding_model_id,
                                WikiPage.is_archived.is_(False),
                                WikiPage.current_version_id.is_not(None),
                            )
                            .order_by(distance)
                            .limit(limit)
                        )
                    ).all()
                    for page_id, raw_distance in semantic_rows:
                        if page_id is None or raw_distance is None:
                            continue
                        similarity = 1 - float(raw_distance)
                        if similarity >= 0.68:
                            scores[page_id] = max(scores.get(page_id, 0), similarity)
            except Exception as exc:
                logger.warning(
                    "wiki_history_embedding_retrieval_failed",
                    document_id=str(document.id),
                    error_type=type(exc).__name__,
                )

        selected_ids = [
            page_id
            for page_id, _score in sorted(scores.items(), key=lambda item: item[1], reverse=True)[
                :limit
            ]
        ]
        if not selected_ids:
            return []
        rows = (
            await self.session.execute(
                select(WikiPage, WikiNode)
                .join(WikiNode, WikiNode.page_id == WikiPage.id)
                .where(
                    WikiPage.id.in_(selected_ids),
                    WikiNode.space_id == self.space_id,
                )
            )
        ).all()
        aliases_by_node: dict[uuid.UUID, list[str]] = {}
        node_ids = [node.id for _page, node in rows]
        if node_ids:
            alias_rows = (
                await self.session.execute(
                    select(WikiNodeAlias.node_id, WikiNodeAlias.alias).where(
                        WikiNodeAlias.node_id.in_(node_ids)
                    )
                )
            ).all()
            for node_id, alias in alias_rows:
                aliases_by_node.setdefault(node_id, []).append(alias)
        candidates = [
            HistoricalWikiNode(
                page_id=page.id,
                node_type=node.node_type,
                title=page.title,
                summary=page.summary,
                slug=page.slug,
                aliases=tuple(dict.fromkeys(aliases_by_node.get(node.id, [page.title]))),
                relevance=scores[page.id],
            )
            for page, node in rows
        ]
        return sorted(candidates, key=lambda item: item.relevance, reverse=True)


async def resolve_exact_alias(
    session: AsyncSession,
    *,
    space_id: uuid.UUID,
    node_type: str,
    title: str,
) -> HistoricalWikiNode | None:
    normalized = normalize_wiki_label(title)
    if not normalized:
        return None
    row = (
        await session.execute(
            select(WikiPage, WikiNode)
            .join(WikiNode, WikiNode.page_id == WikiPage.id)
            .join(WikiNodeAlias, WikiNodeAlias.node_id == WikiNode.id)
            .where(
                WikiNodeAlias.space_id == space_id,
                WikiNodeAlias.normalized_alias == normalized,
                WikiNode.node_type == node_type,
                WikiPage.is_archived.is_(False),
                WikiPage.current_version_id.is_not(None),
            )
            .limit(2)
        )
    ).all()
    if len(row) != 1:
        # Ambiguous aliases are deliberately not auto-resolved.
        return None
    page, node = row[0]
    aliases = tuple(
        (
            await session.scalars(
                select(WikiNodeAlias.alias).where(WikiNodeAlias.node_id == node.id)
            )
        ).all()
    )
    return HistoricalWikiNode(
        page_id=page.id,
        node_type=node.node_type,
        title=page.title,
        summary=page.summary,
        slug=page.slug,
        aliases=aliases,
        relevance=1.0,
    )
