from __future__ import annotations

import json
import re
import unicodedata
import uuid
from collections import defaultdict
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement, SQLColumnExpression

from synapsekb.database.models import (
    AuditLog,
    KnowledgeBase,
    WikiEdge,
    WikiEntityResolution,
    WikiHealthJob,
    WikiNode,
    WikiNodeAlias,
    WikiPage,
    WikiPageSource,
    WikiPageVersion,
    WikiSpace,
)
from synapsekb.database.session import AsyncSessionFactory
from synapsekb.models.provider import DeterministicMockProvider, create_provider
from synapsekb.wiki.entity_resolution import (
    add_node_alias,
    canonicalize_wiki_entity_title,
    ensure_canonical_node_aliases,
    ensure_page_node_embeddings,
    normalize_wiki_label,
)
from synapsekb.wiki.model_selection import resolve_wiki_health_model
from synapsekb.wiki.structured import WIKI_ENTITY_IDENTITY_RULES

logger = structlog.get_logger()

WIKI_HEALTH_REVIEW_MAX_TOKENS = 8_000

_LABEL_TRIGRAM_FLOOR = 0.50
_LABEL_TRIGRAM_CLOSE_MATCH = 0.72
_TECHNICAL_TOKEN = re.compile(r"[a-z][a-z0-9]{1,}|\d{2,}", re.IGNORECASE)
_AUTO_MERGE_IDENTITY_BASES = frozenset(
    {
        "exact_alias",
        "official_name",
        "abbreviation",
        "translation",
        "spelling_variant",
        "scope_variant",
        "same_issuer",
        "non_entity_view",
    }
)
_MODEL_AUTO_DECISION_CONFIDENCE = 0.90
_VERSION_GUARD_EXEMPT_NODE_TYPES = frozenset({"个股", "公司", "企业", "组织"})
_VERSION_MARKER = re.compile(
    r"(?<![0-9a-z])(?:"
    r"v\d+(?:\.\d+)*|"
    r"[a-z]{1,12}\d+(?:\.\d+)*|"
    r"\d+[a-z]+|"
    r"(?<!\.)\d+(?![0-9a-z.]|\.\d)"
    r")(?![0-9a-z])",
    re.IGNORECASE,
)
_NAMED_VERSION_MARKER = re.compile(
    r"(?<![0-9a-z])(?:ultra|pro|max|plus|mini|lite|flash|turbo)(?![0-9a-z])",
    re.IGNORECASE,
)
_CHINESE_GENERATION_MARKER = re.compile(r"(?:第)?[一二三四五六七八九十百\d]+代")
_OBSERVATION_TITLE_SUFFIX = re.compile(
    r"(?:\d+(?:\.\d+)+|上行周期|周期|热潮|(?:与)?融资)$",
    re.IGNORECASE,
)


def _action(action_type: str, **payload: Any) -> dict[str, Any]:
    return {"id": str(uuid.uuid4()), "type": action_type, **payload}


def _unresolved_entity_pair_clause(
    space_id: uuid.UUID,
    left_page_id: SQLColumnExpression[uuid.UUID | None],
    right_page_id: SQLColumnExpression[uuid.UUID | None],
) -> ColumnElement[bool]:
    """Exclude persisted identity decisions before applying candidate limits."""

    resolution_exists = (
        select(WikiEntityResolution.id)
        .where(
            WikiEntityResolution.space_id == space_id,
            WikiEntityResolution.decision.in_(["distinct", "merge"]),
            or_(
                and_(
                    WikiEntityResolution.left_page_id == left_page_id,
                    WikiEntityResolution.right_page_id == right_page_id,
                ),
                and_(
                    WikiEntityResolution.left_page_id == right_page_id,
                    WikiEntityResolution.right_page_id == left_page_id,
                ),
            ),
        )
        .exists()
    )
    return ~resolution_exists


def _candidate_review_priority(candidate: dict[str, Any]) -> tuple[int, int, int, float]:
    """Rank cleanup candidates ahead of merely high lexical overlap.

    This changes only which bounded candidates reach the LLM. It never makes
    an identity decision itself.
    """

    left_label = str(candidate.get("left_label") or "")
    right_label = str(candidate.get("right_label") or "")
    node_type = str(candidate.get("node_type") or "")
    left_normalized = normalize_wiki_label(left_label)
    right_normalized = normalize_wiki_label(right_label)
    left_core = normalize_wiki_label(
        canonicalize_wiki_entity_title(left_label, node_type=node_type)
    )
    right_core = normalize_wiki_label(
        canonicalize_wiki_entity_title(right_label, node_type=node_type)
    )
    containing_label = ""
    if left_normalized and left_normalized in right_normalized:
        containing_label = right_label
    elif right_normalized and right_normalized in left_normalized:
        containing_label = left_label
    observation_variant = bool(
        containing_label and _OBSERVATION_TITLE_SUFFIX.search(containing_label.strip())
    )
    return (
        int(candidate.get("candidate_source") == "alias_exact"),
        int(observation_variant),
        int(bool(left_core) and left_core == right_core),
        float(candidate.get("similarity", 0) or 0),
    )


def is_high_precision_label_candidate(
    left_label: str,
    right_label: str,
    similarity: float,
) -> bool:
    """Gate fuzzy merge candidates without treating topical similarity as identity.

    pg_trgm is useful for coarse lexical recall, but its value is not a
    probability. Medium scores are accepted only when one normalized label
    contains the other or both share a technical identifier such as MLCC.
    """

    left = normalize_wiki_label(left_label)
    right = normalize_wiki_label(right_label)
    if not left or not right or left == right:
        return bool(left and left == right)
    if similarity >= _LABEL_TRIGRAM_CLOSE_MATCH:
        return True
    if similarity < _LABEL_TRIGRAM_FLOOR:
        return False
    if left in right or right in left:
        return True
    left_tokens = {token.casefold() for token in _TECHNICAL_TOKEN.findall(left_label)}
    right_tokens = {token.casefold() for token in _TECHNICAL_TOKEN.findall(right_label)}
    return bool(left_tokens & right_tokens)


def sanitize_wiki_health_report(report: dict[str, Any]) -> dict[str, Any]:
    """Hide legacy embedding-only merge candidates from persisted reports.

    Reports are audit records and stay immutable in the database. Sanitizing on
    read keeps old reports viewable without presenting semantic relatedness as
    entity-name similarity after upgrading the candidate policy.
    """

    sanitized = deepcopy(report)
    raw_candidates = sanitized.get("similar_candidates")
    if not isinstance(raw_candidates, list):
        return sanitized
    candidates = [
        candidate
        for candidate in raw_candidates
        if not (
            isinstance(candidate, dict) and candidate.get("candidate_source") == "embedding_cosine"
        )
    ]
    hidden_count = len(raw_candidates) - len(candidates)
    sanitized["similar_candidates"] = candidates
    summary = sanitized.get("summary")
    if isinstance(summary, dict):
        summary["similar_candidates"] = len(candidates)
    if hidden_count:
        policy = sanitized.setdefault("candidate_policy", {})
        if isinstance(policy, dict):
            policy["version"] = 2
            policy["legacy_semantic_candidates_hidden"] = hidden_count
    return sanitized


def is_auto_merge_eligible(
    candidate: dict[str, Any],
    decision: dict[str, Any],
) -> bool:
    return automatic_merge_block_reason(candidate, decision) is None


def _identity_variant_markers(label: str) -> frozenset[str]:
    normalized = unicodedata.normalize("NFKC", label).casefold()
    return frozenset(
        [match.group(0) for match in _VERSION_MARKER.finditer(normalized)]
        + [match.group(0) for match in _NAMED_VERSION_MARKER.finditer(normalized)]
        + [match.group(0) for match in _CHINESE_GENERATION_MARKER.finditer(normalized)]
    )


def automatic_merge_block_reason(
    candidate: dict[str, Any],
    decision: dict[str, Any],
) -> str | None:
    """Keep only a small deterministic floor below the model decision.

    The model owns semantic identity resolution. Code rejects incomplete
    decisions and explicit version/model/configuration conflicts, because
    merging those pages is lossy and violates the project ontology.
    """

    classification = str(decision.get("classification") or "")
    if classification not in {"merge", "fold_into"}:
        return "模型没有判定为同一实体或可归并的非实体页面"
    confidence = float(decision.get("confidence", 0) or 0)
    if confidence < _MODEL_AUTO_DECISION_CONFIDENCE:
        return (
            f"模型置信度 {confidence:.2f} 未达到自动执行门槛 "
            f"{_MODEL_AUTO_DECISION_CONFIDENCE:.2f}"
        )
    identity_basis = str(decision.get("identity_basis", ""))
    if identity_basis not in _AUTO_MERGE_IDENTITY_BASES:
        return "模型未声明可审计的同一实体依据"
    node_type = str(candidate.get("node_type") or "")
    if node_type not in _VERSION_GUARD_EXEMPT_NODE_TYPES:
        left_markers = _identity_variant_markers(str(candidate.get("left_label") or ""))
        right_markers = _identity_variant_markers(str(candidate.get("right_label") or ""))
        if left_markers != right_markers and (left_markers or right_markers):
            return "名称包含不同版本、型号或配置标记，按项目规则禁止自动合并"
    return None


async def _remove_duplicate_edges(
    session: AsyncSession,
    edges: list[WikiEdge],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[object, ...], list[WikiEdge]] = defaultdict(list)
    for edge in edges:
        grouped[
            (
                edge.source_node_id,
                edge.target_node_id,
                edge.edge_type,
                edge.source_document_id,
                edge.source_page_id,
                edge.evidence.strip(),
            )
        ].append(edge)
    removed: list[dict[str, Any]] = []
    for duplicates in grouped.values():
        for edge in sorted(duplicates, key=lambda item: (item.created_at, item.id))[1:]:
            removed.append(
                _action(
                    "remove_duplicate_edge",
                    edge_id=str(edge.id),
                    reason="完全相同的关系边已存在",
                )
            )
            await session.delete(edge)
    return removed


async def _repair_missing_page_nodes(
    session: AsyncSession,
    space: WikiSpace,
    knowledge_base: KnowledgeBase,
    pages: list[WikiPage],
    page_nodes: dict[uuid.UUID, WikiNode],
) -> list[dict[str, Any]]:
    repaired: list[dict[str, Any]] = []
    for page in pages:
        if page.id in page_nodes:
            continue
        version = (
            await session.get(WikiPageVersion, page.current_version_id)
            if page.current_version_id
            else None
        )
        raw_node_type = version.metadata_json.get("node_type") if version else None
        node_type = (
            raw_node_type
            if isinstance(raw_node_type, str) and raw_node_type in knowledge_base.wiki_node_types
            else knowledge_base.wiki_node_types[0]
        )
        node = WikiNode(
            space_id=space.id,
            node_type=node_type,
            label=page.title,
            page_id=page.id,
            source_page_id=page.id,
            source_time=page.source_time,
            metadata_json={"health_repair": "missing_page_node"},
        )
        session.add(node)
        await session.flush()
        page_nodes[page.id] = node
        repaired.append(
            _action(
                "create_missing_page_node",
                page_id=str(page.id),
                node_id=str(node.id),
                title=page.title,
            )
        )
    return repaired


async def _similar_page_candidates(
    session: AsyncSession,
    space_id: uuid.UUID,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    lexical_pool_limit = min(max(limit * 10, 500), 2000)
    alias_pool_limit = min(max(limit * 3, 150), 1000)
    active_page_ids = select(WikiPage.id).where(
        WikiPage.space_id == space_id,
        WikiPage.is_archived.is_(False),
        WikiPage.current_version_id.is_not(None),
    )
    left = aliased(WikiNode)
    right = aliased(WikiNode)
    score = func.similarity(left.label, right.label)
    lexical_rows = (
        await session.execute(
            select(left, right, score.label("score"))
            .where(
                left.space_id == space_id,
                right.space_id == space_id,
                left.page_id.is_not(None),
                right.page_id.is_not(None),
                left.page_id.in_(active_page_ids),
                right.page_id.in_(active_page_ids),
                left.node_type == right.node_type,
                left.id < right.id,
                _unresolved_entity_pair_clause(space_id, left.page_id, right.page_id),
                # Embedding similarity means topical relatedness, not entity
                # identity. Merge candidates therefore start from name
                # similarity; embeddings are used only as supporting context.
                score >= _LABEL_TRIGRAM_FLOOR,
            )
            .order_by(score.desc())
            .limit(lexical_pool_limit)
        )
    ).all()
    candidates: list[dict[str, Any]] = []
    left_alias = aliased(WikiNodeAlias)
    right_alias = aliased(WikiNodeAlias)
    alias_left_node = aliased(WikiNode)
    alias_right_node = aliased(WikiNode)
    alias_rows = (
        await session.execute(
            select(alias_left_node, alias_right_node, left_alias.alias)
            .join(left_alias, left_alias.node_id == alias_left_node.id)
            .join(
                right_alias,
                right_alias.normalized_alias == left_alias.normalized_alias,
            )
            .join(alias_right_node, alias_right_node.id == right_alias.node_id)
            .where(
                alias_left_node.space_id == space_id,
                alias_right_node.space_id == space_id,
                alias_left_node.page_id.is_not(None),
                alias_right_node.page_id.is_not(None),
                alias_left_node.page_id.in_(active_page_ids),
                alias_right_node.page_id.in_(active_page_ids),
                alias_left_node.node_type == alias_right_node.node_type,
                alias_left_node.id < alias_right_node.id,
                left_alias.normalized_alias != "",
                _unresolved_entity_pair_clause(
                    space_id,
                    alias_left_node.page_id,
                    alias_right_node.page_id,
                ),
            )
            .limit(alias_pool_limit)
        )
    ).all()
    seen_pairs: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for left_node, right_node, matched_alias in alias_rows:
        if left_node.page_id is None or right_node.page_id is None:
            continue
        pair = _page_pair(left_node.page_id, right_node.page_id)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        candidates.append(
            {
                "left_page_id": str(left_node.page_id),
                "left_label": left_node.label,
                "right_page_id": str(right_node.page_id),
                "right_label": right_node.label,
                "node_type": left_node.node_type,
                "similarity": 1.0,
                "candidate_source": "alias_exact",
                "matched_alias": matched_alias,
            }
        )
    for left_node, right_node, similarity in lexical_rows:
        if left_node.page_id is None or right_node.page_id is None:
            continue
        pair = _page_pair(left_node.page_id, right_node.page_id)
        if pair in seen_pairs:
            continue
        raw_similarity = float(similarity)
        if not is_high_precision_label_candidate(
            left_node.label,
            right_node.label,
            raw_similarity,
        ):
            continue
        seen_pairs.add(pair)
        candidates.append(
            {
                "left_page_id": str(left_node.page_id),
                "left_label": left_node.label,
                "right_page_id": str(right_node.page_id),
                "right_label": right_node.label,
                "node_type": left_node.node_type,
                "similarity": round(raw_similarity, 4),
                "candidate_source": "label_trigram",
            }
        )
    candidates.sort(key=_candidate_review_priority, reverse=True)
    selected = candidates[:limit]
    selected_page_ids = {
        uuid.UUID(str(candidate[key]))
        for candidate in selected
        for key in ("left_page_id", "right_page_id")
    }
    page_context = {
        page.id: {
            "summary": page.summary[:300],
            "source_time": page.source_time.isoformat() if page.source_time else None,
        }
        for page in (
            await session.scalars(select(WikiPage).where(WikiPage.id.in_(selected_page_ids)))
        ).all()
    }
    aliases_by_page: dict[uuid.UUID, list[str]] = defaultdict(list)
    if selected_page_ids:
        context_alias_rows = (
            await session.execute(
                select(WikiNode.page_id, WikiNodeAlias.alias)
                .join(WikiNodeAlias, WikiNodeAlias.node_id == WikiNode.id)
                .where(WikiNode.page_id.in_(selected_page_ids))
                .order_by(WikiNodeAlias.created_at)
            )
        ).all()
        for page_id, alias in context_alias_rows:
            if page_id is not None and alias not in aliases_by_page[page_id]:
                aliases_by_page[page_id].append(alias)
    for index, candidate in enumerate(selected, 1):
        candidate["candidate_id"] = str(index)
        for side in ("left", "right"):
            page_id = uuid.UUID(str(candidate[f"{side}_page_id"]))
            context = page_context.get(page_id, {})
            candidate[f"{side}_summary"] = context.get("summary", "")
            candidate[f"{side}_source_time"] = context.get("source_time")
            candidate[f"{side}_aliases"] = aliases_by_page.get(page_id, [])[:5]
    return selected


async def _llm_review(
    session: AsyncSession,
    knowledge_base: KnowledgeBase,
    job: WikiHealthJob,
    similar_candidates: list[dict[str, Any]],
    orphan_pages: list[dict[str, Any]],
    page_catalog: list[dict[str, Any]],
    orphan_neighbors: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], str | None]:
    if not similar_candidates and not orphan_pages:
        return [], None
    try:
        model = await resolve_wiki_health_model(session, knowledge_base, job)
        if job.model_id is None:
            job.model_id = model.id
        provider = create_provider(model)
        if isinstance(provider, DeterministicMockProvider):
            return [], "Mock 模型不能执行 Wiki 健康语义复核"
        try:
            response = await provider.chat_json(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是私有知识库 Wiki 维护器。只做实体消歧和链接建议，不改写事实。"
                            "只返回 JSON 对象："
                            '{"similarity_decisions":[{"candidate_id":"1",'
                            '"classification":"merge|fold_into|related|distinct",'
                            '"canonical":"left|right","confidence":0.0,'
                            '"identity_basis":"exact_alias|official_name|abbreviation|translation|spelling_variant|scope_variant|same_issuer|non_entity_view|none",'
                            '"relation_type":"version_of|configuration_of|subtype_of|part_of|uses|application_of|subsidiary_of|related_to|none",'
                            '"relation_direction":"left_to_right|right_to_left|none",'
                            '"reason":"..."}],'
                            '"orphan_links":[{"source_page_id":"uuid",'
                            '"target_page_id":"uuid","relation_type":"related_to",'
                            '"confidence":0.0,"reason":"..."}]}。'
                            "结论和理由必须简短，不要展示推理过程。"
                            "候选中的名称重合度和别名命中只负责召回，不是同一实体证据。"
                            "merge 只表示完全同一实体。fold_into 表示来源页不是稳定实体，"
                            "而是状态、阶段、观点、组合观察或修辞页面，应将内容和来源归并到"
                            "canonical 指定的稳定核心页后归档；这不表示两个标题是同义词。"
                            "AI资本开支融资、AI资本开支与融资应 fold_into AI资本开支，"
                            "不能仅因融资与资本开支定义不同就保留为平行实体。"
                            "如果判 related，"
                            "应尽量返回方向明确的 relation_type。"
                            "版本/世代/型号/配置必须优先检查，不得因名称包含关系判为 merge，"
                            "也不得把具体版本 fold_into 产品系列。"
                            f"\n\n项目级实体同一性规则：\n{WIKI_ENTITY_IDENTITY_RULES}\n\n"
                            "没有充分证据时不要建议合并或新增关系。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "configured_node_types": knowledge_base.wiki_node_types,
                                "custom_rules": knowledge_base.wiki_generation_prompt,
                                "similar_candidates": similar_candidates,
                                "orphan_pages": orphan_pages[:20],
                                "orphan_neighbor_candidates": orphan_neighbors,
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                max_tokens=WIKI_HEALTH_REVIEW_MAX_TOKENS,
            )
        finally:
            await provider.close()
        payload = json.loads(response)
    except Exception as exc:
        logger.warning(
            "wiki_health_llm_review_failed",
            job_id=str(job.id),
            error_type=type(exc).__name__,
        )
        return [], f"{type(exc).__name__}: {exc}"[:500]

    candidates_by_id = {item["candidate_id"]: item for item in similar_candidates}
    page_ids = {item["page_id"] for item in page_catalog}
    proposals: list[dict[str, Any]] = []
    for decision in payload.get("similarity_decisions", []):
        if not isinstance(decision, dict):
            continue
        candidate = candidates_by_id.get(str(decision.get("candidate_id", "")))
        if candidate is None:
            continue
        classification = str(decision.get("classification") or "distinct")
        confidence = float(decision.get("confidence", 0) or 0)
        candidate["model_classification"] = classification
        candidate["model_confidence"] = confidence
        candidate["model_reason"] = str(decision.get("reason") or "")[:500]
        if confidence < 0.7:
            continue
        canonical = str(decision.get("canonical", "left"))
        target_key = "right_page_id" if canonical == "right" else "left_page_id"
        source_key = "left_page_id" if canonical == "right" else "right_page_id"
        if classification in {"merge", "fold_into"}:
            block_reason = automatic_merge_block_reason(candidate, decision)
            auto_apply = block_reason is None
            identity_basis = str(decision.get("identity_basis") or "")
            proposals.append(
                _action(
                    "merge_pages",
                    target_page_id=candidate[target_key],
                    source_page_ids=[candidate[source_key]],
                    confidence=confidence,
                    identity_basis=identity_basis[:40],
                    resolution_mode=classification,
                    reason=str(decision.get("reason", "LLM 判定为同一节点"))[:500],
                    auto_apply=auto_apply,
                    requires_confirmation=not auto_apply,
                    auto_apply_block_reason=block_reason,
                )
            )
            continue

        if classification not in {"related", "distinct"}:
            continue
        if confidence >= _MODEL_AUTO_DECISION_CONFIDENCE:
            proposals.append(
                _action(
                    "mark_distinct",
                    left_page_id=candidate["left_page_id"],
                    right_page_id=candidate["right_page_id"],
                    confidence=confidence,
                    reason=str(decision.get("reason", "LLM 判定为不同实体"))[:500],
                    auto_apply=True,
                    requires_confirmation=False,
                )
            )
        relation_type = str(decision.get("relation_type") or "none")[:40]
        direction = str(decision.get("relation_direction") or "none")
        if classification != "related" or relation_type == "none" or direction == "none":
            continue
        if direction == "right_to_left":
            relation_source = candidate["right_page_id"]
            relation_target = candidate["left_page_id"]
        else:
            relation_source = candidate["left_page_id"]
            relation_target = candidate["right_page_id"]
        proposals.append(
            _action(
                "add_relation",
                source_page_id=relation_source,
                target_page_id=relation_target,
                relation_type=relation_type,
                confidence=confidence,
                reason=str(decision.get("reason", "LLM 判定为相关实体"))[:500],
                requires_confirmation=True,
            )
        )
    for link in payload.get("orphan_links", []):
        source_page_id = str(link.get("source_page_id", ""))
        target_page_id = str(link.get("target_page_id", ""))
        confidence = float(link.get("confidence", 0) or 0)
        if (
            source_page_id not in page_ids
            or target_page_id not in page_ids
            or source_page_id == target_page_id
            or confidence < 0.75
        ):
            continue
        proposals.append(
            _action(
                "add_relation",
                source_page_id=source_page_id,
                target_page_id=target_page_id,
                relation_type=str(link.get("relation_type") or "related_to")[:40],
                confidence=confidence,
                reason=str(link.get("reason", "LLM 建议补充双链"))[:500],
                requires_confirmation=True,
            )
        )
    return proposals, None


async def _active_merge_destination(
    session: AsyncSession,
    *,
    space_id: uuid.UUID,
    page_id: uuid.UUID,
) -> uuid.UUID | None:
    """Follow merges so one health run can consolidate an alias cluster safely."""

    visited: set[uuid.UUID] = set()
    current_id = page_id
    while current_id not in visited:
        visited.add(current_id)
        page = await session.get(WikiPage, current_id)
        if page is None or page.space_id != space_id:
            return None
        if not page.is_archived and page.current_version_id is not None:
            return page.id
        if page.merged_into_page_id is None:
            return None
        current_id = page.merged_into_page_id
    return None


async def _apply_auto_merge_proposals(
    session: AsyncSession,
    *,
    space: WikiSpace,
    proposals: list[dict[str, Any]],
    similar_candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    pending: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []
    resolved_pairs: set[frozenset[str]] = set()
    for proposal in proposals:
        if proposal.get("type") == "mark_distinct" and proposal.get("auto_apply") is True:
            left_id = str(proposal.get("left_page_id", ""))
            right_id = str(proposal.get("right_page_id", ""))
            confidence = float(proposal.get("confidence", 0) or 0)
            reason = str(proposal.get("reason", "模型判定为不同实体"))[:500]
            try:
                resolution = await record_entity_resolution(
                    session,
                    space_id=space.id,
                    first_page_id=uuid.UUID(left_id),
                    second_page_id=uuid.UUID(right_id),
                    decision="distinct",
                    canonical_page_id=None,
                    reason=(
                        f"Wiki 健康检查模型自动判定为不同实体"
                        f"（置信度 {confidence:.2f}）：{reason}"
                    ),
                    actor_user_id=None,
                    decision_source="llm_auto",
                )
                resolved_pairs.add(frozenset({left_id, right_id}))
                applied.append(
                    {
                        "id": str(resolution.id),
                        "type": "mark_distinct",
                        "left_page_id": left_id,
                        "right_page_id": right_id,
                        "confidence": confidence,
                        "decision_source": "llm_auto",
                        "reason": resolution.reason,
                    }
                )
            except (RuntimeError, ValueError) as exc:
                pending.append(
                    {
                        **proposal,
                        "auto_apply": False,
                        "requires_confirmation": True,
                        "auto_apply_error": f"{type(exc).__name__}: {exc}"[:500],
                    }
                )
            continue
        if proposal.get("type") != "merge_pages" or proposal.get("auto_apply") is not True:
            pending.append(proposal)
            continue
        source_ids = [str(value) for value in proposal.get("source_page_ids", [])]
        target_id = str(proposal.get("target_page_id", ""))
        if not target_id or len(source_ids) != 1:
            pending.append({**proposal, "requires_confirmation": True, "auto_apply": False})
            continue
        source_id = source_ids[0]
        raw_pair = frozenset({target_id, source_id})
        effective_target_id = await _active_merge_destination(
            session,
            space_id=space.id,
            page_id=uuid.UUID(target_id),
        )
        effective_source_id = await _active_merge_destination(
            session,
            space_id=space.id,
            page_id=uuid.UUID(source_id),
        )
        if effective_target_id is None or effective_source_id is None:
            pending.append(
                {
                    **proposal,
                    "auto_apply": False,
                    "requires_confirmation": True,
                    "auto_apply_error": "合并页面不存在或无法解析到当前有效页面",
                }
            )
            continue
        if effective_target_id == effective_source_id:
            resolved_pairs.add(raw_pair)
            continue
        target_id = str(effective_target_id)
        source_id = str(effective_source_id)
        confidence = float(proposal.get("confidence", 0) or 0)
        identity_basis = str(proposal.get("identity_basis", "none"))
        resolution_mode = str(proposal.get("resolution_mode") or "merge")
        reason = str(proposal.get("reason", "模型判定为同一实体或应归并页面"))[:500]
        operation_label = "归并非实体页面" if resolution_mode == "fold_into" else "合并"
        change_summary = (
            f"Wiki 健康检查模型自动{operation_label}"
            f"（置信度 {confidence:.2f}，依据 {identity_basis}）：{reason}"
        )
        try:
            await merge_wiki_pages(
                session,
                space=space,
                target_page_id=uuid.UUID(target_id),
                source_page_ids=[uuid.UUID(source_id)],
                change_summary=change_summary,
                actor_user_id=None,
                decision_source="llm_auto",
            )
            left_page_id, right_page_id = _page_pair(
                uuid.UUID(target_id),
                uuid.UUID(source_id),
            )
            merge_resolution = await session.scalar(
                select(WikiEntityResolution).where(
                    WikiEntityResolution.space_id == space.id,
                    WikiEntityResolution.left_page_id == left_page_id,
                    WikiEntityResolution.right_page_id == right_page_id,
                    WikiEntityResolution.decision == "merge",
                )
            )
            if merge_resolution is None:
                raise RuntimeError("自动合并完成但缺少实体消歧记录")
            resolved_pairs.add(raw_pair)
            resolved_pairs.add(frozenset({target_id, source_id}))
            applied.append(
                {
                    "id": str(merge_resolution.id),
                    "type": "merge_pages",
                    "target_page_id": target_id,
                    "source_page_ids": [source_id],
                    "confidence": confidence,
                    "identity_basis": identity_basis,
                    "resolution_mode": resolution_mode,
                    "decision_source": "llm_auto",
                    "reason": change_summary,
                    "reversible": True,
                }
            )
        except (RuntimeError, ValueError) as exc:
            pending.append(
                {
                    **proposal,
                    "auto_apply": False,
                    "requires_confirmation": True,
                    "auto_apply_error": f"{type(exc).__name__}: {exc}"[:500],
                }
            )
    remaining_candidates = [
        candidate
        for candidate in similar_candidates
        if frozenset(
            {
                str(candidate.get("left_page_id", "")),
                str(candidate.get("right_page_id", "")),
            }
        )
        not in resolved_pairs
    ]
    active_page_ids = {
        str(page_id)
        for page_id in (
            await session.scalars(
                select(WikiPage.id).where(
                    WikiPage.space_id == space.id,
                    WikiPage.is_archived.is_(False),
                    WikiPage.current_version_id.is_not(None),
                )
            )
        ).all()
    }
    remaining_candidates = [
        candidate
        for candidate in remaining_candidates
        if str(candidate.get("left_page_id", "")) in active_page_ids
        and str(candidate.get("right_page_id", "")) in active_page_ids
    ]
    pending = [
        proposal
        for proposal in pending
        if (
            proposal.get("type") == "merge_pages"
            and str(proposal.get("target_page_id", "")) in active_page_ids
            and all(
                str(page_id) in active_page_ids for page_id in proposal.get("source_page_ids", [])
            )
        )
        or (
            proposal.get("type") == "add_relation"
            and str(proposal.get("source_page_id", "")) in active_page_ids
            and str(proposal.get("target_page_id", "")) in active_page_ids
        )
    ]
    return pending, applied, remaining_candidates


async def _orphan_neighbor_candidates(
    session: AsyncSession,
    *,
    space_id: uuid.UUID,
    orphan_pages: list[dict[str, Any]],
    page_nodes: dict[uuid.UUID, WikiNode],
    limit_per_page: int = 4,
) -> dict[str, list[dict[str, Any]]]:
    """Retrieve a bounded local catalog for orphan-link review."""

    result: dict[str, list[dict[str, Any]]] = {}
    for orphan in orphan_pages[:12]:
        page_id = uuid.UUID(orphan["page_id"])
        source_node = page_nodes.get(page_id)
        if source_node is None:
            continue
        if source_node.embedding is not None:
            distance = WikiNode.embedding.cosine_distance(source_node.embedding)
            rows = (
                await session.execute(
                    select(WikiNode, WikiPage, distance.label("distance"))
                    .join(WikiPage, WikiPage.id == WikiNode.page_id)
                    .where(
                        WikiNode.space_id == space_id,
                        WikiNode.page_id.is_not(None),
                        WikiNode.id != source_node.id,
                        WikiNode.embedding.is_not(None),
                        WikiPage.is_archived.is_(False),
                        WikiPage.current_version_id.is_not(None),
                    )
                    .order_by(distance)
                    .limit(limit_per_page)
                )
            ).all()
            result[str(page_id)] = [
                {
                    "page_id": str(page.id),
                    "title": page.title,
                    "node_type": node.node_type,
                    "semantic_similarity": round(1 - float(raw_distance), 4),
                }
                for node, page, raw_distance in rows
                if raw_distance is not None
            ]
        else:
            score = func.similarity(WikiNode.label, source_node.label)
            rows = (
                await session.execute(
                    select(WikiNode, WikiPage, score.label("score"))
                    .join(WikiPage, WikiPage.id == WikiNode.page_id)
                    .where(
                        WikiNode.space_id == space_id,
                        WikiNode.page_id.is_not(None),
                        WikiNode.id != source_node.id,
                        WikiPage.is_archived.is_(False),
                    )
                    .order_by(score.desc())
                    .limit(limit_per_page)
                )
            ).all()
            result[str(page_id)] = [
                {
                    "page_id": str(page.id),
                    "title": page.title,
                    "node_type": node.node_type,
                    "name_similarity": round(float(raw_score), 4),
                }
                for node, page, raw_score in rows
            ]
    return result


async def run_wiki_health_job(job_id: uuid.UUID) -> None:
    async with AsyncSessionFactory() as session:
        job = await session.get(WikiHealthJob, job_id)
        if job is None or job.status == "completed":
            return
        job.status = "running"
        job.started_at = datetime.now(UTC)
        await session.commit()
        try:
            space = await session.get(WikiSpace, job.space_id)
            if space is None or space.published_version is None:
                raise RuntimeError("Wiki 尚未发布")
            knowledge_base = await session.get(KnowledgeBase, space.knowledge_base_id)
            if knowledge_base is None:
                raise RuntimeError("知识库不存在")
            pages = list(
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
            nodes = list(
                (await session.scalars(select(WikiNode).where(WikiNode.space_id == space.id))).all()
            )
            edges = list(
                (await session.scalars(select(WikiEdge).where(WikiEdge.space_id == space.id))).all()
            )
            page_nodes = {node.page_id: node for node in nodes if node.page_id is not None}
            source_count_rows = (
                await session.execute(
                    select(WikiPageVersion.page_id, func.count(WikiPageSource.id))
                    .join(
                        WikiPageSource,
                        WikiPageSource.page_version_id == WikiPageVersion.id,
                        isouter=True,
                    )
                    .where(WikiPageVersion.id.in_([page.current_version_id for page in pages]))
                    .group_by(WikiPageVersion.page_id)
                )
            ).all()
            source_counts: dict[uuid.UUID, int] = {
                page_id: int(count) for page_id, count in source_count_rows
            }
            applied: list[dict[str, Any]] = []
            if job.auto_repair:
                applied.extend(
                    await _repair_missing_page_nodes(
                        session, space, knowledge_base, pages, page_nodes
                    )
                )
                applied.extend(await _remove_duplicate_edges(session, edges))
                await session.flush()

            await ensure_canonical_node_aliases(session, list(page_nodes.values()))
            embedded_nodes, embedding_error = await ensure_page_node_embeddings(
                session,
                knowledge_base,
                pages,
                page_nodes,
            )

            connected_node_ids = {
                node_id for edge in edges for node_id in (edge.source_node_id, edge.target_node_id)
            }
            page_node_ids = {node.id for node in page_nodes.values()}
            page_links = {
                node_id
                for edge in edges
                if edge.source_node_id in page_node_ids and edge.target_node_id in page_node_ids
                for node_id in (edge.source_node_id, edge.target_node_id)
            }
            orphan_pages = [
                {
                    "page_id": str(page.id),
                    "title": page.title,
                    "summary": page.summary[:300],
                    "node_type": page_nodes[page.id].node_type,
                }
                for page in pages
                if page.id in page_nodes and page_nodes[page.id].id not in page_links
            ]
            isolated_nodes = [
                {
                    "node_id": str(node.id),
                    "page_id": str(node.page_id) if node.page_id else None,
                    "label": node.label,
                    "node_type": node.node_type,
                }
                for node in nodes
                if node.id not in connected_node_ids
            ]
            missing_sources = [
                {"page_id": str(page.id), "title": page.title}
                for page in pages
                if not source_counts.get(page.id, 0)
            ]
            similar_candidates = await _similar_page_candidates(session, space.id)
            pages_by_id = {page.id: page for page in pages}
            for candidate in similar_candidates:
                left_page = pages_by_id.get(uuid.UUID(candidate["left_page_id"]))
                right_page = pages_by_id.get(uuid.UUID(candidate["right_page_id"]))
                candidate["left_summary"] = left_page.summary[:300] if left_page else ""
                candidate["right_summary"] = right_page.summary[:300] if right_page else ""
                candidate["left_source_count"] = (
                    source_counts.get(left_page.id, 0) if left_page else 0
                )
                candidate["right_source_count"] = (
                    source_counts.get(right_page.id, 0) if right_page else 0
                )
            page_catalog = [
                {
                    "page_id": str(page.id),
                    "title": page.title,
                    "summary": page.summary[:240],
                    "node_type": page_nodes[page.id].node_type,
                }
                for page in pages
                if page.id in page_nodes
            ]
            orphan_neighbors = await _orphan_neighbor_candidates(
                session,
                space_id=space.id,
                orphan_pages=orphan_pages,
                page_nodes=page_nodes,
            )
            await session.refresh(job)
            if job.cancel_requested_at is not None:
                job.status = "cancelled"
                job.finished_at = datetime.now(UTC)
                await session.commit()
                return
            proposals, llm_error = await _llm_review(
                session,
                knowledge_base,
                job,
                similar_candidates,
                orphan_pages,
                page_catalog,
                orphan_neighbors,
            )
            if job.auto_repair and llm_error is None:
                proposals, automatic_resolutions, similar_candidates = (
                    await _apply_auto_merge_proposals(
                        session,
                        space=space,
                        proposals=proposals,
                        similar_candidates=similar_candidates,
                    )
                )
                applied.extend(automatic_resolutions)
                automatic_merges = [
                    action
                    for action in automatic_resolutions
                    if action.get("type") == "merge_pages"
                ]
                automatic_distinct = [
                    action
                    for action in automatic_resolutions
                    if action.get("type") == "mark_distinct"
                ]
            else:
                automatic_resolutions = []
                automatic_merges = []
                automatic_distinct = []
            job.report = {
                "checked_at": datetime.now(UTC).isoformat(),
                "page_count": len(pages),
                "node_count": len(nodes),
                "edge_count": len(edges),
                "orphan_pages": orphan_pages,
                "isolated_nodes": isolated_nodes,
                "missing_sources": missing_sources,
                "similar_candidates": similar_candidates,
                "orphan_neighbor_candidates": orphan_neighbors,
                "llm_review_error": llm_error,
                "embedding_error": embedding_error,
                "candidate_policy": {
                    "version": 6,
                    "identity_gate": (
                        "exact_alias_or_label_trigram>=0.50_with_lexical_identity_guard"
                    ),
                    "embedding_role": "history_retrieval_and_relation_context_only",
                    "score_semantics": "lexical_overlap_not_identity_probability",
                    "automatic_merge": (
                        "LLM exact-identity decision with confidence>=0.90 and an explicit "
                        "identity basis; no additional deterministic identity anchor; every "
                        "merge is audited and reversible"
                    ),
                    "version_policy": (
                        "series, generation, version, model and configuration are distinct "
                        "entities and are connected by typed relationships"
                    ),
                    "non_entity_page_policy": (
                        "status, phase, opinion and composite observation pages may fold into "
                        "a stable core page without claiming semantic identity"
                    ),
                },
                "summary": {
                    "orphan_pages": len(orphan_pages),
                    "isolated_nodes": len(isolated_nodes),
                    "missing_sources": len(missing_sources),
                    "similar_candidates": len(similar_candidates),
                    "proposed_actions": len(proposals),
                    "auto_repaired": len(applied),
                    "auto_merged": len(automatic_merges),
                    "auto_marked_distinct": len(automatic_distinct),
                    "embedded_nodes_updated": embedded_nodes,
                    "embedded_nodes_total": sum(
                        1 for node in page_nodes.values() if node.embedding is not None
                    ),
                },
            }
            job.proposed_actions = proposals
            job.applied_actions = applied
            job.status = "completed"
            job.finished_at = datetime.now(UTC)
            session.add(
                AuditLog(
                    actor_user_id=None,
                    action="wiki.health.completed",
                    resource_type="wiki_health_job",
                    resource_id=job.id,
                    metadata_json=job.report["summary"],
                    created_at=datetime.now(UTC),
                )
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            job = await session.get(WikiHealthJob, job_id)
            if job is not None and job.status != "cancelled":
                job.status = "failed"
                job.error_summary = f"{type(exc).__name__}: {exc}"[:1000]
                job.finished_at = datetime.now(UTC)
                await session.commit()
            raise


async def _deduplicate_space_edges(session: AsyncSession, space_id: uuid.UUID) -> None:
    edges = list(
        (
            await session.scalars(
                select(WikiEdge)
                .where(WikiEdge.space_id == space_id)
                .order_by(WikiEdge.created_at, WikiEdge.id)
            )
        ).all()
    )
    seen: set[tuple[object, ...]] = set()
    for edge in edges:
        key = (
            edge.source_node_id,
            edge.target_node_id,
            edge.edge_type,
            edge.source_document_id,
            edge.source_page_id,
            edge.evidence.strip(),
        )
        if edge.source_node_id == edge.target_node_id or key in seen:
            await session.delete(edge)
        else:
            seen.add(key)


def _page_pair(
    first_page_id: uuid.UUID,
    second_page_id: uuid.UUID,
) -> tuple[uuid.UUID, uuid.UUID]:
    left, right = sorted((first_page_id, second_page_id))
    return left, right


async def record_entity_resolution(
    session: AsyncSession,
    *,
    space_id: uuid.UUID,
    first_page_id: uuid.UUID,
    second_page_id: uuid.UUID,
    decision: str,
    canonical_page_id: uuid.UUID | None,
    reason: str,
    actor_user_id: uuid.UUID | None,
    decision_source: str = "manual",
    merge_group_id: uuid.UUID | None = None,
    snapshot_json: dict[str, Any] | None = None,
) -> WikiEntityResolution:
    if decision not in {"distinct", "merge"}:
        raise ValueError("不支持的实体消歧结论")
    if first_page_id == second_page_id:
        raise ValueError("不能对同一页面执行实体消歧")
    left_page_id, right_page_id = _page_pair(first_page_id, second_page_id)
    resolution = await session.scalar(
        select(WikiEntityResolution)
        .where(
            WikiEntityResolution.space_id == space_id,
            WikiEntityResolution.left_page_id == left_page_id,
            WikiEntityResolution.right_page_id == right_page_id,
        )
        .with_for_update()
    )
    if resolution is None:
        resolution = WikiEntityResolution(
            space_id=space_id,
            left_page_id=left_page_id,
            right_page_id=right_page_id,
            decision=decision,
            canonical_page_id=canonical_page_id,
            reason=reason,
            decision_source=decision_source,
            decided_by_user_id=actor_user_id,
            merge_group_id=merge_group_id,
            snapshot_json=snapshot_json or {},
        )
        session.add(resolution)
    else:
        resolution.decision = decision
        resolution.canonical_page_id = canonical_page_id
        resolution.reason = reason
        resolution.decision_source = decision_source
        resolution.decided_by_user_id = actor_user_id
        resolution.merge_group_id = merge_group_id
        resolution.snapshot_json = snapshot_json or {}
        resolution.reverted_at = None
    await session.flush()
    return resolution


def _strip_primary_heading(content: str) -> str:
    lines = content.strip().splitlines()
    if lines and lines[0].lstrip().startswith("# "):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines.pop(0)
    return "\n".join(lines).strip()


def compose_merged_markdown(
    target_title: str,
    target_content: str,
    source_contents: list[tuple[str, str]],
) -> str:
    """Losslessly combine pages while keeping each source section auditable."""

    sections = [f"# {target_title}"]
    target_body = _strip_primary_heading(target_content)
    if target_body:
        sections.append(target_body)
    seen_bodies = {" ".join(target_body.split())} if target_body else set()
    for source_title, source_content in source_contents:
        source_body = _strip_primary_heading(source_content)
        normalized = " ".join(source_body.split())
        if not source_body or normalized in seen_bodies:
            continue
        seen_bodies.add(normalized)
        sections.append(f"## 合并自：{source_title}\n\n{source_body}")
    return "\n\n---\n\n".join(sections)


def _merged_relation_metadata(
    versions: list[WikiPageVersion],
) -> list[dict[str, Any]]:
    relations: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for version in versions:
        raw_relations = version.metadata_json.get("relations", [])
        if not isinstance(raw_relations, list):
            continue
        for relation in raw_relations:
            if not isinstance(relation, dict):
                continue
            key = (
                str(relation.get("target_slug") or ""),
                str(relation.get("type") or "related_to"),
                str(relation.get("evidence") or ""),
            )
            if not key[0] or key in seen:
                continue
            seen.add(key)
            relations.append(dict(relation))
    return relations


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


async def _build_merge_snapshot(
    session: AsyncSession,
    *,
    target: WikiPage,
    old_target_version_id: uuid.UUID,
    merged_version_id: uuid.UUID,
    target_summary: str,
    target_source_time: datetime | None,
    sources: list[WikiPage],
    source_nodes: list[WikiNode],
    merge_alias_source: str,
) -> dict[str, Any]:
    source_node_ids = [node.id for node in source_nodes]
    aliases = (
        list(
            (
                await session.scalars(
                    select(WikiNodeAlias).where(WikiNodeAlias.node_id.in_(source_node_ids))
                )
            ).all()
        )
        if source_node_ids
        else []
    )
    edges = (
        list(
            (
                await session.scalars(
                    select(WikiEdge).where(
                        WikiEdge.space_id == target.space_id,
                        or_(
                            WikiEdge.source_node_id.in_(source_node_ids),
                            WikiEdge.target_node_id.in_(source_node_ids),
                        ),
                    )
                )
            ).all()
        )
        if source_node_ids
        else []
    )
    return {
        "schema_version": 1,
        "target_page_id": str(target.id),
        "old_target_version_id": str(old_target_version_id),
        "merged_version_id": str(merged_version_id),
        "target_summary": target_summary,
        "target_source_time": _isoformat(target_source_time),
        "merge_alias_source": merge_alias_source,
        "source_pages": [
            {
                "id": str(source.id),
                "current_version_id": str(source.current_version_id),
                "summary": source.summary,
                "source_time": _isoformat(source.source_time),
            }
            for source in sources
        ],
        "source_nodes": [
            {
                "id": str(node.id),
                "node_type": node.node_type,
                "label": node.label,
                "page_id": str(node.page_id) if node.page_id else None,
                "document_id": str(node.document_id) if node.document_id else None,
                "source_document_id": (
                    str(node.source_document_id) if node.source_document_id else None
                ),
                "source_page_id": str(node.source_page_id) if node.source_page_id else None,
                "source_time": _isoformat(node.source_time),
                "metadata": node.metadata_json,
            }
            for node in source_nodes
        ],
        "source_aliases": [
            {
                "node_id": str(alias.node_id),
                "alias": alias.alias,
                "source": alias.source,
            }
            for alias in aliases
        ],
        "edges": [
            {
                "id": str(edge.id),
                "source_node_id": str(edge.source_node_id),
                "target_node_id": str(edge.target_node_id),
                "edge_type": edge.edge_type,
                "evidence": edge.evidence,
                "source_document_id": (
                    str(edge.source_document_id) if edge.source_document_id else None
                ),
                "source_page_id": str(edge.source_page_id) if edge.source_page_id else None,
                "source_time": _isoformat(edge.source_time),
            }
            for edge in edges
        ],
    }


async def _mark_health_candidate_resolved(
    session: AsyncSession,
    *,
    health_job_id: uuid.UUID | None,
    space_id: uuid.UUID,
    first_page_id: uuid.UUID,
    second_page_id: uuid.UUID,
    action: dict[str, Any],
) -> None:
    if health_job_id is None:
        return
    job = await session.scalar(
        select(WikiHealthJob)
        .where(WikiHealthJob.id == health_job_id, WikiHealthJob.space_id == space_id)
        .with_for_update()
    )
    if job is None:
        return
    pair = {str(first_page_id), str(second_page_id)}
    report = dict(job.report)
    candidates = report.get("similar_candidates", [])
    if isinstance(candidates, list):
        report["similar_candidates"] = [
            candidate
            for candidate in candidates
            if not (
                isinstance(candidate, dict)
                and {
                    str(candidate.get("left_page_id", "")),
                    str(candidate.get("right_page_id", "")),
                }
                == pair
            )
        ]
    summary = dict(report.get("summary", {}))
    summary["similar_candidates"] = len(report.get("similar_candidates", []))
    report["summary"] = summary
    job.report = report
    job.applied_actions = [*job.applied_actions, action]


async def merge_wiki_pages(
    session: AsyncSession,
    *,
    space: WikiSpace,
    target_page_id: uuid.UUID,
    source_page_ids: list[uuid.UUID],
    change_summary: str,
    actor_user_id: uuid.UUID | None,
    health_job_id: uuid.UUID | None = None,
    decision_source: str = "manual",
) -> WikiPage:
    unique_source_ids = list(dict.fromkeys(source_page_ids))
    if target_page_id in unique_source_ids:
        raise ValueError("目标页面不能同时作为来源页面")
    target = await session.scalar(
        select(WikiPage)
        .where(WikiPage.id == target_page_id, WikiPage.space_id == space.id)
        .with_for_update()
    )
    if target is None or target.current_version_id is None or target.is_archived:
        raise ValueError("合并目标页面不存在或不可用")
    sources = list(
        (
            await session.scalars(
                select(WikiPage)
                .where(
                    WikiPage.id.in_(unique_source_ids),
                    WikiPage.space_id == space.id,
                    WikiPage.current_version_id.is_not(None),
                    WikiPage.is_archived.is_(False),
                )
                .with_for_update()
            )
        ).all()
    )
    if len(sources) != len(unique_source_ids):
        raise ValueError("部分来源页面不存在、已归档或不属于同一 Wiki")
    target_summary_before = target.summary
    target_source_time_before = target.source_time
    target_version = await session.get(WikiPageVersion, target.current_version_id)
    if target_version is None:
        raise ValueError("目标页面当前版本不存在")
    source_versions = [
        version
        for source in sources
        if (version := await session.get(WikiPageVersion, source.current_version_id)) is not None
    ]
    if len(source_versions) != len(sources):
        raise ValueError("部分来源页面当前版本不存在")
    merged_content = compose_merged_markdown(
        target.title,
        target_version.content,
        [
            (source.title, version.content)
            for source, version in zip(sources, source_versions, strict=True)
        ],
    )
    version_number = (
        await session.scalar(
            select(func.max(WikiPageVersion.version_number)).where(
                WikiPageVersion.page_id == target.id
            )
        )
        or 0
    ) + 1
    source_times = [
        value
        for value in [target.source_time, *(source.source_time for source in sources)]
        if value is not None
    ]
    merged_version = WikiPageVersion(
        page_id=target.id,
        version_number=version_number,
        content=merged_content,
        protected_blocks=list(
            dict.fromkeys(
                [
                    *target_version.protected_blocks,
                    *(block for version in source_versions for block in version.protected_blocks),
                ]
            )
        ),
        change_summary=change_summary,
        is_manual=True,
        source_time=max(source_times) if source_times else None,
        metadata_json={
            **target_version.metadata_json,
            "merged_from_page_ids": [str(source.id) for source in sources],
            "merged_from_titles": [source.title for source in sources],
            "relations": _merged_relation_metadata([target_version, *source_versions]),
        },
    )
    session.add(merged_version)
    await session.flush()
    all_version_ids = [target_version.id, *(version.id for version in source_versions)]
    all_sources = list(
        (
            await session.scalars(
                select(WikiPageSource).where(WikiPageSource.page_version_id.in_(all_version_ids))
            )
        ).all()
    )
    copied_source_keys: set[tuple[object, ...]] = set()
    for page_source in all_sources:
        key = (
            page_source.document_id,
            page_source.chunk_id,
            page_source.paragraph_key,
        )
        if key in copied_source_keys:
            continue
        copied_source_keys.add(key)
        session.add(
            WikiPageSource(
                page_version_id=merged_version.id,
                document_id=page_source.document_id,
                chunk_id=page_source.chunk_id,
                paragraph_key=page_source.paragraph_key,
                evidence_text=page_source.evidence_text,
                source_time=page_source.source_time,
            )
        )
    target.current_version_id = merged_version.id
    target.source_time = merged_version.source_time
    merged_summaries = list(
        dict.fromkeys(
            summary.strip()
            for summary in [target.summary, *(source.summary for source in sources)]
            if summary.strip()
        )
    )
    target.summary = "；".join(merged_summaries)[:1000] or merged_version.content[:300]
    target_node = await session.scalar(
        select(WikiNode).where(WikiNode.space_id == space.id, WikiNode.page_id == target.id)
    )
    if target_node is None:
        target_node = WikiNode(
            space_id=space.id,
            node_type=str(target_version.metadata_json.get("node_type") or "主题"),
            label=target.title,
            page_id=target.id,
            source_page_id=target.id,
            source_time=target.source_time,
            metadata_json={"health_repair": "merge_target_node"},
        )
        session.add(target_node)
        await session.flush()
    await add_node_alias(
        session,
        node=target_node,
        alias=target.title,
        source="canonical",
    )
    target_node.source_time = target.source_time
    target_node.embedding = None
    target_node.embedding_model_id = None
    source_nodes = list(
        (
            await session.scalars(
                select(WikiNode).where(
                    WikiNode.space_id == space.id,
                    WikiNode.page_id.in_(unique_source_ids),
                )
            )
        ).all()
    )
    source_node_ids = [node.id for node in source_nodes]
    merge_group_id = uuid.uuid4()
    merge_alias_source = f"merge:{merge_group_id.hex[:20]}"
    merge_snapshot = await _build_merge_snapshot(
        session,
        target=target,
        old_target_version_id=target_version.id,
        merged_version_id=merged_version.id,
        target_summary=target_summary_before,
        target_source_time=target_source_time_before,
        sources=sources,
        source_nodes=source_nodes,
        merge_alias_source=merge_alias_source,
    )
    if source_node_ids:
        source_aliases = list(
            (
                await session.scalars(
                    select(WikiNodeAlias).where(WikiNodeAlias.node_id.in_(source_node_ids))
                )
            ).all()
        )
        for alias in source_aliases:
            await add_node_alias(
                session,
                node=target_node,
                alias=alias.alias,
                source=merge_alias_source,
            )
    for source in sources:
        await add_node_alias(
            session,
            node=target_node,
            alias=source.title,
            source=merge_alias_source,
        )
    if source_node_ids:
        await session.execute(
            update(WikiEdge)
            .where(WikiEdge.source_node_id.in_(source_node_ids))
            .values(source_node_id=target_node.id)
        )
        await session.execute(
            update(WikiEdge)
            .where(WikiEdge.target_node_id.in_(source_node_ids))
            .values(target_node_id=target_node.id)
        )
        await session.execute(delete(WikiNode).where(WikiNode.id.in_(source_node_ids)))
    for source in sources:
        source.is_archived = True
        source.merged_into_page_id = target.id
        resolution = await record_entity_resolution(
            session,
            space_id=space.id,
            first_page_id=target.id,
            second_page_id=source.id,
            decision="merge",
            canonical_page_id=target.id,
            reason=change_summary,
            actor_user_id=actor_user_id,
            decision_source=decision_source,
            merge_group_id=merge_group_id,
            snapshot_json=merge_snapshot,
        )
        await _mark_health_candidate_resolved(
            session,
            health_job_id=health_job_id,
            space_id=space.id,
            first_page_id=target.id,
            second_page_id=source.id,
            action={
                "id": str(resolution.id),
                "type": "merge_pages",
                "target_page_id": str(target.id),
                "source_page_ids": [str(source.id)],
                "reason": change_summary,
            },
        )
    await _deduplicate_space_edges(session, space.id)
    space.published_version = (space.published_version or 0) + 1
    session.add(
        AuditLog(
            actor_user_id=actor_user_id,
            action="wiki.pages.merge",
            resource_type="wiki_page",
            resource_id=target.id,
            metadata_json={"source_page_ids": [str(source.id) for source in sources]},
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()
    await session.refresh(target)
    return target


def _snapshot_uuid(value: object) -> uuid.UUID | None:
    return uuid.UUID(str(value)) if value else None


def _snapshot_datetime(value: object) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value else None


async def undo_wiki_page_merge(
    session: AsyncSession,
    *,
    space: WikiSpace,
    resolution_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> WikiPage:
    resolution = await session.scalar(
        select(WikiEntityResolution)
        .where(
            WikiEntityResolution.id == resolution_id,
            WikiEntityResolution.space_id == space.id,
            WikiEntityResolution.decision == "merge",
            WikiEntityResolution.reverted_at.is_(None),
        )
        .with_for_update()
    )
    if resolution is None:
        raise ValueError("合并记录不存在或已经撤销")
    snapshot = resolution.snapshot_json
    if snapshot.get("schema_version") != 1 or resolution.merge_group_id is None:
        raise ValueError("该历史合并没有完整快照，不能自动撤销")
    target_page_id = _snapshot_uuid(snapshot.get("target_page_id"))
    old_target_version_id = _snapshot_uuid(snapshot.get("old_target_version_id"))
    merged_version_id = _snapshot_uuid(snapshot.get("merged_version_id"))
    if target_page_id is None or old_target_version_id is None or merged_version_id is None:
        raise ValueError("合并快照缺少目标版本信息")
    target = await session.scalar(
        select(WikiPage)
        .where(WikiPage.id == target_page_id, WikiPage.space_id == space.id)
        .with_for_update()
    )
    if target is None:
        raise ValueError("合并目标页面不存在")
    if target.is_archived or target.merged_into_page_id is not None:
        raise ValueError("该合并结果后来又合入其他节点，请先撤销更新的外层合并")
    if target.current_version_id != merged_version_id:
        raise ValueError("目标页面在合并后又发生了修改，请先处理新版本后再撤销")

    raw_source_pages = snapshot.get("source_pages", [])
    raw_source_nodes = snapshot.get("source_nodes", [])
    raw_source_aliases = snapshot.get("source_aliases", [])
    raw_edges = snapshot.get("edges", [])
    if not all(
        isinstance(items, list)
        for items in (raw_source_pages, raw_source_nodes, raw_source_aliases, raw_edges)
    ):
        raise ValueError("合并快照格式无效")

    source_page_ids = [
        page_id
        for item in raw_source_pages
        if isinstance(item, dict) and (page_id := _snapshot_uuid(item.get("id"))) is not None
    ]
    source_pages = list(
        (
            await session.scalars(
                select(WikiPage)
                .where(WikiPage.id.in_(source_page_ids), WikiPage.space_id == space.id)
                .with_for_update()
            )
        ).all()
    )
    if len(source_pages) != len(source_page_ids):
        raise ValueError("部分来源页面已被删除，不能自动撤销")
    source_pages_by_id = {page.id: page for page in source_pages}
    for raw_page in raw_source_pages:
        if not isinstance(raw_page, dict):
            continue
        page_id = _snapshot_uuid(raw_page.get("id"))
        source_page = source_pages_by_id.get(page_id) if page_id else None
        if source_page is None or source_page.merged_into_page_id != target.id:
            raise ValueError("来源页面状态已发生变化，不能自动撤销")
        source_page.current_version_id = _snapshot_uuid(raw_page.get("current_version_id"))
        source_page.summary = str(raw_page.get("summary") or "")
        source_page.source_time = _snapshot_datetime(raw_page.get("source_time"))
        source_page.is_archived = False
        source_page.merged_into_page_id = None

    restored_nodes: dict[uuid.UUID, WikiNode] = {}
    for raw_node in raw_source_nodes:
        if not isinstance(raw_node, dict):
            continue
        node_id = _snapshot_uuid(raw_node.get("id"))
        if node_id is None:
            continue
        node = await session.get(WikiNode, node_id)
        if node is None:
            node = WikiNode(id=node_id, space_id=space.id)
            session.add(node)
        node.node_type = str(raw_node.get("node_type") or "主题")[:30]
        node.label = str(raw_node.get("label") or "")[:500]
        node.page_id = _snapshot_uuid(raw_node.get("page_id"))
        node.document_id = _snapshot_uuid(raw_node.get("document_id"))
        node.source_document_id = _snapshot_uuid(raw_node.get("source_document_id"))
        node.source_page_id = _snapshot_uuid(raw_node.get("source_page_id"))
        node.source_time = _snapshot_datetime(raw_node.get("source_time"))
        node.embedding = None
        node.embedding_model_id = None
        raw_metadata = raw_node.get("metadata")
        node.metadata_json = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
        restored_nodes[node_id] = node
    await session.flush()

    for raw_alias in raw_source_aliases:
        if not isinstance(raw_alias, dict):
            continue
        node_id = _snapshot_uuid(raw_alias.get("node_id"))
        node = restored_nodes.get(node_id) if node_id else None
        alias = str(raw_alias.get("alias") or "").strip()
        if node is not None and alias:
            await add_node_alias(
                session,
                node=node,
                alias=alias,
                source=str(raw_alias.get("source") or "canonical")[:32],
            )

    for raw_edge in raw_edges:
        if not isinstance(raw_edge, dict):
            continue
        edge_id = _snapshot_uuid(raw_edge.get("id"))
        source_node_id = _snapshot_uuid(raw_edge.get("source_node_id"))
        target_node_id = _snapshot_uuid(raw_edge.get("target_node_id"))
        if edge_id is None or source_node_id is None or target_node_id is None:
            continue
        edge = await session.get(WikiEdge, edge_id)
        if edge is None:
            edge = WikiEdge(id=edge_id, space_id=space.id)
            session.add(edge)
        edge.source_node_id = source_node_id
        edge.target_node_id = target_node_id
        edge.edge_type = str(raw_edge.get("edge_type") or "related_to")[:40]
        edge.evidence = str(raw_edge.get("evidence") or "")[:4000]
        edge.source_document_id = _snapshot_uuid(raw_edge.get("source_document_id"))
        edge.source_page_id = _snapshot_uuid(raw_edge.get("source_page_id"))
        edge.source_time = _snapshot_datetime(raw_edge.get("source_time"))

    merge_alias_source = str(snapshot.get("merge_alias_source") or "")
    if merge_alias_source:
        await session.execute(
            delete(WikiNodeAlias).where(
                WikiNodeAlias.space_id == space.id,
                WikiNodeAlias.source == merge_alias_source,
            )
        )
    target.current_version_id = old_target_version_id
    target.summary = str(snapshot.get("target_summary") or "")
    target.source_time = _snapshot_datetime(snapshot.get("target_source_time"))
    target_node = await session.scalar(
        select(WikiNode).where(WikiNode.space_id == space.id, WikiNode.page_id == target.id)
    )
    if target_node is not None:
        target_node.source_time = target.source_time
        target_node.embedding = None
        target_node.embedding_model_id = None

    reverted_at = datetime.now(UTC)
    group_resolutions = list(
        (
            await session.scalars(
                select(WikiEntityResolution).where(
                    WikiEntityResolution.space_id == space.id,
                    WikiEntityResolution.merge_group_id == resolution.merge_group_id,
                )
            )
        ).all()
    )
    resolution_ids = {str(item.id) for item in group_resolutions}
    for item in group_resolutions:
        item.decision = "reverted"
        item.reverted_at = reverted_at
    health_jobs = list(
        (
            await session.scalars(
                select(WikiHealthJob)
                .where(WikiHealthJob.space_id == space.id)
                .order_by(WikiHealthJob.created_at.desc())
                .limit(20)
            )
        ).all()
    )
    for job in health_jobs:
        changed = False
        actions: list[dict[str, Any]] = []
        for action in job.applied_actions:
            updated_action = dict(action)
            if str(updated_action.get("id")) in resolution_ids:
                updated_action["reverted_at"] = reverted_at.isoformat()
                changed = True
            actions.append(updated_action)
        if changed:
            job.applied_actions = actions
    await _deduplicate_space_edges(session, space.id)
    space.published_version = (space.published_version or 0) + 1
    session.add(
        AuditLog(
            actor_user_id=actor_user_id,
            action="wiki.pages.merge.undo",
            resource_type="wiki_entity_resolution",
            resource_id=resolution.id,
            metadata_json={
                "merge_group_id": str(resolution.merge_group_id),
                "target_page_id": str(target.id),
                "source_page_ids": [str(page_id) for page_id in source_page_ids],
            },
            created_at=reverted_at,
        )
    )
    await session.commit()
    await session.refresh(target)
    return target


async def mark_wiki_pages_distinct(
    session: AsyncSession,
    *,
    space: WikiSpace,
    left_page_id: uuid.UUID,
    right_page_id: uuid.UUID,
    reason: str,
    actor_user_id: uuid.UUID,
    health_job_id: uuid.UUID | None = None,
) -> WikiEntityResolution:
    pages = list(
        (
            await session.scalars(
                select(WikiPage).where(
                    WikiPage.space_id == space.id,
                    WikiPage.id.in_([left_page_id, right_page_id]),
                    WikiPage.current_version_id.is_not(None),
                    WikiPage.is_archived.is_(False),
                )
            )
        ).all()
    )
    if len(pages) != 2:
        raise ValueError("相似候选页面不存在、已归档或不属于同一 Wiki")
    resolution = await record_entity_resolution(
        session,
        space_id=space.id,
        first_page_id=left_page_id,
        second_page_id=right_page_id,
        decision="distinct",
        canonical_page_id=None,
        reason=reason,
        actor_user_id=actor_user_id,
    )
    await _mark_health_candidate_resolved(
        session,
        health_job_id=health_job_id,
        space_id=space.id,
        first_page_id=left_page_id,
        second_page_id=right_page_id,
        action={
            "id": str(resolution.id),
            "type": "mark_distinct",
            "left_page_id": str(left_page_id),
            "right_page_id": str(right_page_id),
            "reason": reason,
        },
    )
    session.add(
        AuditLog(
            actor_user_id=actor_user_id,
            action="wiki.entity.mark_distinct",
            resource_type="wiki_entity_resolution",
            resource_id=resolution.id,
            metadata_json={
                "left_page_id": str(left_page_id),
                "right_page_id": str(right_page_id),
            },
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()
    await session.refresh(resolution)
    return resolution


async def add_wiki_page_relation(
    session: AsyncSession,
    *,
    space: WikiSpace,
    source_page_id: uuid.UUID,
    target_page_id: uuid.UUID,
    relation_type: str,
    evidence: str,
    actor_user_id: uuid.UUID,
    health_job_id: uuid.UUID | None = None,
    proposal_id: uuid.UUID | None = None,
) -> WikiEdge:
    if source_page_id == target_page_id:
        raise ValueError("不能创建页面到自身的关系")
    nodes = list(
        (
            await session.scalars(
                select(WikiNode).where(
                    WikiNode.space_id == space.id,
                    WikiNode.page_id.in_([source_page_id, target_page_id]),
                )
            )
        ).all()
    )
    by_page = {node.page_id: node for node in nodes}
    source_node = by_page.get(source_page_id)
    target_node = by_page.get(target_page_id)
    if source_node is None or target_node is None:
        raise ValueError("关系两端必须是当前 Wiki 中的页面节点")
    existing = await session.scalar(
        select(WikiEdge).where(
            WikiEdge.space_id == space.id,
            WikiEdge.source_node_id == source_node.id,
            WikiEdge.target_node_id == target_node.id,
            WikiEdge.edge_type == relation_type,
        )
    )
    if existing is None:
        source_times = [
            value
            for value in (source_node.source_time, target_node.source_time)
            if value is not None
        ]
        edge = WikiEdge(
            space_id=space.id,
            source_node_id=source_node.id,
            target_node_id=target_node.id,
            edge_type=relation_type,
            evidence=evidence,
            source_page_id=source_page_id,
            source_time=max(source_times) if source_times else None,
        )
        session.add(edge)
        await session.flush()
        session.add(
            AuditLog(
                actor_user_id=actor_user_id,
                action="wiki.relation.create",
                resource_type="wiki_edge",
                resource_id=edge.id,
                metadata_json={
                    "source_page_id": str(source_page_id),
                    "target_page_id": str(target_page_id),
                    "relation_type": relation_type,
                },
                created_at=datetime.now(UTC),
            )
        )
    else:
        edge = existing
    await _mark_health_relation_proposal_applied(
        session,
        health_job_id=health_job_id,
        proposal_id=proposal_id,
        space_id=space.id,
        source_page_id=source_page_id,
        target_page_id=target_page_id,
        relation_type=relation_type,
        edge_id=edge.id,
    )
    await session.commit()
    await session.refresh(edge)
    return edge


def _apply_health_relation_proposal(
    job: WikiHealthJob,
    *,
    proposal_id: uuid.UUID,
    source_page_id: uuid.UUID,
    target_page_id: uuid.UUID,
    relation_type: str,
    edge_id: uuid.UUID,
) -> bool:
    proposal_id_text = str(proposal_id)
    matched_action = next(
        (
            action
            for action in job.proposed_actions
            if action.get("type") == "add_relation"
            and str(action.get("id", "")) == proposal_id_text
            and str(action.get("source_page_id", "")) == str(source_page_id)
            and str(action.get("target_page_id", "")) == str(target_page_id)
            and str(action.get("relation_type", "related_to")) == relation_type
        ),
        None,
    )
    if matched_action is None:
        return False
    job.proposed_actions = [
        action for action in job.proposed_actions if str(action.get("id", "")) != proposal_id_text
    ]
    report = dict(job.report)
    summary = dict(report.get("summary", {}))
    summary["proposed_actions"] = len(job.proposed_actions)
    report["summary"] = summary
    job.report = report
    if not any(
        action.get("type") == "add_relation"
        and str(action.get("proposal_id", "")) == proposal_id_text
        for action in job.applied_actions
    ):
        job.applied_actions = [
            *job.applied_actions,
            _action(
                "add_relation",
                proposal_id=proposal_id_text,
                edge_id=str(edge_id),
                source_page_id=str(source_page_id),
                target_page_id=str(target_page_id),
                relation_type=relation_type,
                reason=str(matched_action.get("reason", "管理员确认 Wiki 关系"))[:500],
            ),
        ]
    return True


async def _mark_health_relation_proposal_applied(
    session: AsyncSession,
    *,
    health_job_id: uuid.UUID | None,
    proposal_id: uuid.UUID | None,
    space_id: uuid.UUID,
    source_page_id: uuid.UUID,
    target_page_id: uuid.UUID,
    relation_type: str,
    edge_id: uuid.UUID,
) -> None:
    if health_job_id is None or proposal_id is None:
        return
    job = await session.scalar(
        select(WikiHealthJob)
        .where(WikiHealthJob.id == health_job_id, WikiHealthJob.space_id == space_id)
        .with_for_update()
    )
    if job is None:
        return
    _apply_health_relation_proposal(
        job,
        proposal_id=proposal_id,
        source_page_id=source_page_id,
        target_page_id=target_page_id,
        relation_type=relation_type,
        edge_id=edge_id,
    )
