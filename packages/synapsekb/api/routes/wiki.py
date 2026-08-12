from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from pydantic import AwareDatetime
from sqlalchemy import ColumnElement, and_, func, or_, select, true

from apps.wiki_worker.actors import check_wiki_health, generate_wiki
from synapsekb.api.schemas import (
    TimeFilter,
    WikiAddRelationRequest,
    WikiEntityDecisionRequest,
    WikiGenerateRequest,
    WikiGraphSearchRequest,
    WikiHealthJobRead,
    WikiHealthStartRequest,
    WikiJobRead,
    WikiMergePagesRequest,
    WikiPageContent,
    WikiPageEdit,
    WikiPageRead,
    WikiPageSourceRead,
    WikiPageVersionRead,
)
from synapsekb.auth.dependencies import CurrentUser, DatabaseSession
from synapsekb.auth.policy import require_knowledge_base_access
from synapsekb.database.models import (
    Document,
    KnowledgeBase,
    WikiEdge,
    WikiEntityResolution,
    WikiHealthJob,
    WikiNode,
    WikiPage,
    WikiPageSource,
    WikiPageVersion,
    WikiSpace,
    WikiUpdateJob,
)
from synapsekb.domain.enums import TimeField
from synapsekb.wiki.health import (
    add_wiki_page_relation,
    mark_wiki_pages_distinct,
    merge_wiki_pages,
    sanitize_wiki_health_report,
    undo_wiki_page_merge,
)
from synapsekb.wiki.model_selection import (
    WikiModelConfigurationError,
    resolve_wiki_health_model,
    resolve_wiki_model,
)

router = APIRouter()


async def _published_space(
    session: DatabaseSession,
    user: CurrentUser,
    knowledge_base_id: uuid.UUID,
    *,
    write: bool = False,
) -> WikiSpace:
    await require_knowledge_base_access(session, user, knowledge_base_id, write=write)
    space = await session.scalar(
        select(WikiSpace).where(WikiSpace.knowledge_base_id == knowledge_base_id)
    )
    if space is None or space.published_version is None:
        raise HTTPException(status_code=404, detail="Wiki 尚未发布")
    return space


async def _page_source_reads(
    session: DatabaseSession,
    version_id: uuid.UUID,
) -> list[WikiPageSourceRead]:
    rows = (
        await session.execute(
            select(WikiPageSource, Document.title)
            .join(Document, Document.id == WikiPageSource.document_id)
            .where(WikiPageSource.page_version_id == version_id)
        )
    ).all()
    return [
        WikiPageSourceRead(
            document_id=source.document_id,
            document_name=document_title,
            chunk_id=source.chunk_id,
            paragraph_key=source.paragraph_key,
            evidence_text=source.evidence_text,
            source_time=source.source_time,
        )
        for source, document_title in rows
    ]


async def _space(
    session: DatabaseSession,
    user: CurrentUser,
    knowledge_base_id: uuid.UUID,
) -> WikiSpace:
    return await _published_space(session, user, knowledge_base_id)


@router.get("/{knowledge_base_id}/index.md", response_class=PlainTextResponse)
async def wiki_index_markdown(
    knowledge_base_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> str:
    space = await _space(session, user, knowledge_base_id)
    rows = (
        await session.execute(
            select(WikiPage, WikiNode.node_type, func.count(WikiPageSource.id))
            .join(
                WikiNode,
                and_(WikiNode.space_id == space.id, WikiNode.page_id == WikiPage.id),
                isouter=True,
            )
            .join(
                WikiPageSource,
                WikiPageSource.page_version_id == WikiPage.current_version_id,
                isouter=True,
            )
            .where(
                WikiPage.space_id == space.id,
                WikiPage.current_version_id.is_not(None),
                WikiPage.is_archived.is_(False),
            )
            .group_by(WikiPage.id, WikiNode.node_type)
            .order_by(WikiNode.node_type, WikiPage.title)
        )
    ).all()
    groups: dict[str, list[str]] = {}
    for page, node_type, source_count in rows:
        timestamp = page.source_time.isoformat() if page.source_time else "时间未知"
        groups.setdefault(node_type or "页面", []).append(
            f"- [{page.title}](/wiki?kb={knowledge_base_id}&page={page.id}) — "
            f"{page.summary[:120].replace(chr(10), ' ')} "
            f"（source_time: {timestamp}，来源: {source_count}）"
        )
    lines = ["# Wiki Index", "", f"> published_version: {space.published_version}", ""]
    for node_type, entries in groups.items():
        lines.extend([f"## {node_type}", "", *entries, ""])
    return "\n".join(lines)


@router.get("/{knowledge_base_id}/index", response_model=list[WikiPageRead])
async def wiki_index(
    knowledge_base_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
    time_field: TimeField = TimeField.SOURCE_TIME,
    from_time: AwareDatetime | None = None,
    to_time: AwareDatetime | None = None,
    include_unknown: bool = False,
) -> list[WikiPageRead]:
    space = await _space(session, user, knowledge_base_id)
    if from_time is not None and to_time is not None and to_time < from_time:
        raise HTTPException(status_code=422, detail="to_time 必须晚于 from_time")
    time_clause = _wiki_page_time_clause(
        time_field,
        from_time,
        to_time,
        include_unknown,
    )
    node_type = (
        select(WikiNode.node_type)
        .where(
            WikiNode.space_id == space.id,
            WikiNode.page_id == WikiPage.id,
        )
        .limit(1)
        .scalar_subquery()
    )
    rows = (
        await session.execute(
            select(WikiPage, node_type.label("node_type"))
            .where(
                WikiPage.space_id == space.id,
                WikiPage.current_version_id.is_not(None),
                WikiPage.is_archived.is_(False),
                time_clause,
            )
            .order_by(WikiPage.sort_order, WikiPage.title)
        )
    ).all()
    return [
        WikiPageRead.model_validate(page).model_copy(
            update={"node_type": page_node_type or "页面"},
        )
        for page, page_node_type in rows
    ]


@router.get("/pages/{page_id}", response_model=WikiPageContent)
async def wiki_read(
    page_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> WikiPageContent:
    page = await session.get(WikiPage, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Wiki 页面不存在")
    space = await session.get(WikiSpace, page.space_id)
    if space is None:
        raise HTTPException(status_code=404, detail="Wiki 空间不存在")
    await require_knowledge_base_access(session, user, space.knowledge_base_id)
    if page.current_version_id is None:
        raise HTTPException(status_code=404, detail="Wiki 页面尚未发布")
    version = await session.get(WikiPageVersion, page.current_version_id)
    if version is None:
        raise HTTPException(status_code=500, detail="Wiki 当前版本损坏")
    sources = await _page_source_reads(session, version.id)
    return WikiPageContent(
        **WikiPageRead.model_validate(page).model_dump(),
        content=version.content,
        version_number=version.version_number,
        protected_blocks=version.protected_blocks,
        sources=sources,
    )


@router.get("/pages/{page_id}/relations")
async def wiki_page_relations(
    page_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> dict[str, object]:
    page = await session.get(WikiPage, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Wiki 页面不存在")
    space = await session.get(WikiSpace, page.space_id)
    if space is None:
        raise HTTPException(status_code=404, detail="Wiki 空间不存在")
    await require_knowledge_base_access(session, user, space.knowledge_base_id)
    center = await session.scalar(
        select(WikiNode).where(
            WikiNode.space_id == space.id,
            WikiNode.page_id == page.id,
        )
    )
    if center is None:
        return {"nodes": [], "edges": []}
    edges = list(
        (
            await session.scalars(
                select(WikiEdge).where(
                    WikiEdge.space_id == space.id,
                    or_(
                        WikiEdge.source_node_id == center.id,
                        WikiEdge.target_node_id == center.id,
                    ),
                )
            )
        ).all()
    )
    node_ids = {center.id} | {
        node_id for edge in edges for node_id in (edge.source_node_id, edge.target_node_id)
    }
    nodes = list(
        (
            await session.scalars(
                select(WikiNode).where(
                    WikiNode.space_id == space.id,
                    WikiNode.id.in_(node_ids),
                )
            )
        ).all()
    )
    return _graph_payload(nodes, edges)


async def _editable_page(
    page_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> tuple[WikiPage, WikiSpace]:
    page = await session.get(WikiPage, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Wiki 页面不存在")
    space = await session.get(WikiSpace, page.space_id)
    if space is None:
        raise HTTPException(status_code=404, detail="Wiki 空间不存在")
    await require_knowledge_base_access(
        session,
        user,
        space.knowledge_base_id,
        write=True,
    )
    return page, space


@router.get("/pages/{page_id}/versions", response_model=list[WikiPageVersionRead])
async def wiki_page_versions(
    page_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> list[WikiPageVersion]:
    page = await session.get(WikiPage, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Wiki 页面不存在")
    space = await session.get(WikiSpace, page.space_id)
    if space is None:
        raise HTTPException(status_code=404, detail="Wiki 空间不存在")
    await require_knowledge_base_access(session, user, space.knowledge_base_id)
    return list(
        (
            await session.scalars(
                select(WikiPageVersion)
                .where(WikiPageVersion.page_id == page.id)
                .order_by(WikiPageVersion.version_number.desc())
            )
        ).all()
    )


@router.patch("/pages/{page_id}", response_model=WikiPageContent)
async def edit_wiki_page(
    page_id: uuid.UUID,
    payload: WikiPageEdit,
    user: CurrentUser,
    session: DatabaseSession,
) -> WikiPageContent:
    page, space = await _editable_page(page_id, user, session)
    current_sources = list(
        (
            await session.scalars(
                select(WikiPageSource).where(
                    WikiPageSource.page_version_id == page.current_version_id
                )
            )
        ).all()
    )
    current_version = (
        await session.get(WikiPageVersion, page.current_version_id)
        if page.current_version_id is not None
        else None
    )
    version_number = (
        await session.scalar(
            select(func.max(WikiPageVersion.version_number)).where(
                WikiPageVersion.page_id == page.id
            )
        )
        or 0
    ) + 1
    version = WikiPageVersion(
        page_id=page.id,
        version_number=version_number,
        content=payload.content,
        protected_blocks=payload.protected_blocks,
        change_summary=payload.change_summary,
        is_manual=True,
        source_time=(
            payload.source_time if "source_time" in payload.model_fields_set else page.source_time
        ),
        metadata_json=dict(current_version.metadata_json) if current_version else {},
    )
    session.add(version)
    await session.flush()
    for source in current_sources:
        session.add(
            WikiPageSource(
                page_version_id=version.id,
                document_id=source.document_id,
                chunk_id=source.chunk_id,
                paragraph_key=source.paragraph_key,
                evidence_text=source.evidence_text,
                source_time=source.source_time,
            )
        )
    page.current_version_id = version.id
    page.source_time = version.source_time
    space.published_version = (space.published_version or 0) + 1
    await session.commit()
    return WikiPageContent(
        **WikiPageRead.model_validate(page).model_dump(),
        content=version.content,
        version_number=version.version_number,
        protected_blocks=version.protected_blocks,
        sources=[WikiPageSourceRead.model_validate(source) for source in current_sources],
    )


@router.post(
    "/pages/{page_id}/rollback/{version_id}",
    response_model=WikiPageContent,
)
async def rollback_wiki_page(
    page_id: uuid.UUID,
    version_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> WikiPageContent:
    page, space = await _editable_page(page_id, user, session)
    source_version = await session.scalar(
        select(WikiPageVersion).where(
            WikiPageVersion.id == version_id,
            WikiPageVersion.page_id == page.id,
        )
    )
    if source_version is None:
        raise HTTPException(status_code=404, detail="Wiki 历史版本不存在")
    version_number = (
        await session.scalar(
            select(func.max(WikiPageVersion.version_number)).where(
                WikiPageVersion.page_id == page.id
            )
        )
        or 0
    ) + 1
    restored = WikiPageVersion(
        page_id=page.id,
        version_number=version_number,
        content=source_version.content,
        protected_blocks=source_version.protected_blocks,
        change_summary=f"回滚自版本 {source_version.version_number}",
        is_manual=True,
        source_time=source_version.source_time,
        metadata_json=dict(source_version.metadata_json),
    )
    session.add(restored)
    await session.flush()
    old_sources = list(
        (
            await session.scalars(
                select(WikiPageSource).where(WikiPageSource.page_version_id == source_version.id)
            )
        ).all()
    )
    for source in old_sources:
        session.add(
            WikiPageSource(
                page_version_id=restored.id,
                document_id=source.document_id,
                chunk_id=source.chunk_id,
                paragraph_key=source.paragraph_key,
                evidence_text=source.evidence_text,
                source_time=source.source_time,
            )
        )
    page.current_version_id = restored.id
    page.source_time = restored.source_time
    space.published_version = (space.published_version or 0) + 1
    await session.commit()
    return WikiPageContent(
        **WikiPageRead.model_validate(page).model_dump(),
        content=restored.content,
        version_number=restored.version_number,
        protected_blocks=restored.protected_blocks,
        sources=[WikiPageSourceRead.model_validate(source) for source in old_sources],
    )


@router.get("/{knowledge_base_id}/search", response_model=list[WikiPageRead])
async def wiki_search(
    knowledge_base_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
    query: str = Query(min_length=1, max_length=500),
    time_field: TimeField = TimeField.SOURCE_TIME,
    from_time: AwareDatetime | None = None,
    to_time: AwareDatetime | None = None,
    include_unknown: bool = False,
) -> list[WikiPage]:
    space = await _space(session, user, knowledge_base_id)
    if from_time is not None and to_time is not None and to_time < from_time:
        raise HTTPException(status_code=422, detail="to_time 必须晚于 from_time")
    time_clause = _wiki_page_time_clause(
        time_field,
        from_time,
        to_time,
        include_unknown,
    )
    return list(
        (
            await session.scalars(
                select(WikiPage)
                .where(
                    WikiPage.space_id == space.id,
                    WikiPage.current_version_id.is_not(None),
                    WikiPage.is_archived.is_(False),
                    time_clause,
                    or_(
                        WikiPage.title.ilike(f"%{query}%"),
                        WikiPage.summary.ilike(f"%{query}%"),
                    ),
                )
                .limit(50)
            )
        ).all()
    )


def _wiki_page_time_clause(
    field: TimeField,
    from_time: datetime | None,
    to_time: datetime | None,
    include_unknown: bool,
) -> ColumnElement[bool]:
    if from_time is None and to_time is None:
        return true()
    column = {
        TimeField.SOURCE_TIME: WikiPage.source_time,
        TimeField.CREATED_AT: WikiPage.created_at,
        TimeField.UPDATED_AT: WikiPage.updated_at,
    }[field]
    conditions: list[ColumnElement[bool]] = [column.is_not(None)]
    if from_time is not None:
        conditions.append(column >= from_time)
    if to_time is not None:
        conditions.append(column <= to_time)
    known = and_(*conditions)
    return or_(known, column.is_(None)) if include_unknown else known


def _graph_time_clause(
    model: type[WikiNode] | type[WikiEdge],
    time_filter: TimeFilter | None,
) -> ColumnElement[bool]:
    if time_filter is None:
        return true()
    columns = {
        TimeField.SOURCE_TIME: model.source_time,
        TimeField.CREATED_AT: model.created_at,
        TimeField.UPDATED_AT: model.updated_at,
    }
    column = columns[time_filter.field]
    clauses: list[ColumnElement[bool]] = [column.is_not(None)]
    if time_filter.from_:
        clauses.append(column >= time_filter.from_)
    if time_filter.to:
        clauses.append(column <= time_filter.to)
    known = and_(*clauses)
    return or_(known, column.is_(None)) if time_filter.include_unknown else known


def _graph_payload(
    nodes: list[WikiNode],
    edges: list[WikiEdge],
    *,
    meta: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "nodes": [
            {
                "id": str(node.id),
                "type": node.node_type,
                "label": node.label,
                "page_id": str(node.page_id) if node.page_id else None,
                "document_id": str(node.document_id) if node.document_id else None,
                "source_time": node.source_time,
                "metadata": node.metadata_json,
            }
            for node in nodes
        ],
        "edges": [
            {
                "id": str(edge.id),
                "source": str(edge.source_node_id),
                "target": str(edge.target_node_id),
                "type": edge.edge_type,
                "evidence": edge.evidence,
                "source_time": edge.source_time,
                "source_document_id": edge.source_document_id,
                "source_page_id": edge.source_page_id,
            }
            for edge in edges
        ],
    }
    if meta is not None:
        payload["meta"] = meta
    return payload


def _strict_graph_subset(
    nodes: list[WikiNode],
    edges: list[WikiEdge],
    node_types: list[str] | None,
) -> tuple[list[WikiNode], list[WikiEdge]]:
    """Apply the requested node-type whitelist and remove dangling edges."""
    if node_types is None:
        visible_nodes = nodes
    else:
        allowed = set(node_types)
        visible_nodes = [node for node in nodes if node.node_type in allowed]
    visible_ids = {node.id for node in visible_nodes}
    visible_edges = [
        edge
        for edge in edges
        if edge.source_node_id in visible_ids and edge.target_node_id in visible_ids
    ]
    return visible_nodes, visible_edges


@router.post("/{knowledge_base_id}/graph/neighbors")
async def wiki_graph_neighbors(
    knowledge_base_id: uuid.UUID,
    node_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
    time_filter: TimeFilter | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, object]:
    space = await _space(session, user, knowledge_base_id)
    center = await session.scalar(
        select(WikiNode).where(WikiNode.id == node_id, WikiNode.space_id == space.id)
    )
    if center is None:
        raise HTTPException(status_code=404, detail="图节点不存在")
    edges = list(
        (
            await session.scalars(
                select(WikiEdge)
                .where(
                    WikiEdge.space_id == space.id,
                    or_(
                        WikiEdge.source_node_id == node_id,
                        WikiEdge.target_node_id == node_id,
                    ),
                    _graph_time_clause(WikiEdge, time_filter),
                )
                .limit(limit)
            )
        ).all()
    )
    node_ids = {item for edge in edges for item in (edge.source_node_id, edge.target_node_id)}
    nodes = list(
        (
            await session.scalars(
                select(WikiNode).where(
                    WikiNode.id.in_(node_ids),
                    _graph_time_clause(WikiNode, time_filter),
                )
            )
        ).all()
    )
    nodes, edges = _strict_graph_subset(nodes, edges, None)
    return _graph_payload(nodes, edges)


@router.post("/{knowledge_base_id}/graph/search")
async def wiki_graph_search(
    knowledge_base_id: uuid.UUID,
    payload: WikiGraphSearchRequest,
    user: CurrentUser,
    session: DatabaseSession,
) -> dict[str, object]:
    space = await _space(session, user, knowledge_base_id)
    if payload.node_types == []:
        return _graph_payload(
            [],
            [],
            meta={
                "mode": payload.mode,
                "total_nodes": 0,
                "total_edges": 0,
                "matched_nodes": 0,
                "returned_nodes": 0,
                "returned_edges": 0,
                "limit": payload.limit,
                "truncated": False,
            },
        )
    node_scope_clauses = [
        WikiNode.space_id == space.id,
        _graph_time_clause(WikiNode, payload.time_filter),
    ]
    if payload.node_types is not None:
        node_scope_clauses.append(WikiNode.node_type.in_(payload.node_types))
    node_match_clauses = list(node_scope_clauses)
    if payload.query:
        node_match_clauses.append(WikiNode.label.ilike(f"%{payload.query}%"))
    edge_scope_clauses = [
        WikiEdge.space_id == space.id,
        _graph_time_clause(WikiEdge, payload.time_filter),
    ]
    scoped_node_ids = select(WikiNode.id).where(*node_scope_clauses)
    edge_scope_clauses.extend(
        [
            WikiEdge.source_node_id.in_(scoped_node_ids),
            WikiEdge.target_node_id.in_(scoped_node_ids),
        ]
    )
    total_nodes = int(
        await session.scalar(select(func.count(WikiNode.id)).where(*node_scope_clauses)) or 0
    )
    matched_nodes = int(
        await session.scalar(select(func.count(WikiNode.id)).where(*node_match_clauses)) or 0
    )
    total_edges = int(
        await session.scalar(select(func.count(WikiEdge.id)).where(*edge_scope_clauses)) or 0
    )

    if payload.mode == "overview":
        incident_node_ids = (
            select(WikiEdge.source_node_id.label("node_id"))
            .where(*edge_scope_clauses)
            .union_all(select(WikiEdge.target_node_id.label("node_id")).where(*edge_scope_clauses))
            .subquery()
        )
        degree_counts = (
            select(
                incident_node_ids.c.node_id,
                func.count().label("degree"),
            )
            .group_by(incident_node_ids.c.node_id)
            .subquery()
        )
        nodes = list(
            (
                await session.scalars(
                    select(WikiNode)
                    .outerjoin(degree_counts, degree_counts.c.node_id == WikiNode.id)
                    .where(*node_match_clauses)
                    .order_by(
                        func.coalesce(degree_counts.c.degree, 0).desc(),
                        WikiNode.label.asc(),
                    )
                    .limit(payload.limit)
                )
            ).all()
        )
        node_ids = [node.id for node in nodes]
        edges = list(
            (
                await session.scalars(
                    select(WikiEdge)
                    .where(
                        *edge_scope_clauses,
                        WikiEdge.source_node_id.in_(node_ids),
                        WikiEdge.target_node_id.in_(node_ids),
                    )
                    .order_by(WikiEdge.updated_at.desc())
                    .limit(min(payload.limit * 8, 2000))
                )
            ).all()
        )
    else:
        seed_limit = max(1, payload.limit // 2) if payload.query else payload.limit
        seed_nodes = list(
            (
                await session.scalars(
                    select(WikiNode)
                    .where(*node_match_clauses)
                    .order_by(WikiNode.updated_at.desc(), WikiNode.label.asc())
                    .limit(seed_limit)
                )
            ).all()
        )
        seed_ids = [node.id for node in seed_nodes]
        edges = list(
            (
                await session.scalars(
                    select(WikiEdge)
                    .where(
                        *edge_scope_clauses,
                        or_(
                            WikiEdge.source_node_id.in_(seed_ids),
                            WikiEdge.target_node_id.in_(seed_ids),
                        ),
                    )
                    .order_by(WikiEdge.updated_at.desc())
                    .limit(min(payload.limit * 6, 1200))
                )
            ).all()
        )
        candidate_ids = list(seed_ids)
        seen_ids = set(candidate_ids)
        for edge in edges:
            for adjacent_id in (edge.source_node_id, edge.target_node_id):
                if adjacent_id in seen_ids:
                    continue
                if len(candidate_ids) >= payload.limit:
                    break
                seen_ids.add(adjacent_id)
                candidate_ids.append(adjacent_id)
            if len(candidate_ids) >= payload.limit:
                break
        nodes = list(
            (
                await session.scalars(
                    select(WikiNode).where(
                        WikiNode.id.in_(candidate_ids),
                        _graph_time_clause(WikiNode, payload.time_filter),
                    )
                )
            ).all()
        )
    nodes, edges = _strict_graph_subset(nodes, edges, payload.node_types)
    visible_ids = {node.id for node in nodes}
    edges = [
        edge
        for edge in edges
        if edge.source_node_id in visible_ids and edge.target_node_id in visible_ids
    ]
    return _graph_payload(
        nodes,
        edges,
        meta={
            "mode": payload.mode,
            "total_nodes": total_nodes,
            "total_edges": total_edges,
            "matched_nodes": matched_nodes,
            "returned_nodes": len(nodes),
            "returned_edges": len(edges),
            "limit": payload.limit,
            "truncated": matched_nodes > len(nodes) or total_nodes > len(nodes),
        },
    )


@router.post("/generate", response_model=WikiJobRead, status_code=status.HTTP_202_ACCEPTED)
async def start_wiki_generation(
    payload: WikiGenerateRequest,
    user: CurrentUser,
    session: DatabaseSession,
) -> WikiUpdateJob:
    await require_knowledge_base_access(
        session,
        user,
        payload.knowledge_base_id,
        write=True,
    )
    space = await session.scalar(
        select(WikiSpace).where(WikiSpace.knowledge_base_id == payload.knowledge_base_id)
    )
    if space is None:
        space = WikiSpace(knowledge_base_id=payload.knowledge_base_id)
        session.add(space)
        await session.flush()
    knowledge_base = await session.get(KnowledgeBase, payload.knowledge_base_id)
    if knowledge_base is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    try:
        model = await resolve_wiki_model(session, knowledge_base)
    except WikiModelConfigurationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    active = await session.scalar(
        select(WikiUpdateJob)
        .where(
            WikiUpdateJob.space_id == space.id,
            WikiUpdateJob.status.in_(["queued", "running", "quality_check"]),
        )
        .with_for_update()
    )
    if active is not None:
        raise HTTPException(status_code=409, detail="该 Wiki 已有进行中的生成任务")
    job = WikiUpdateJob(
        space_id=space.id,
        model_id=model.id,
        status="queued",
        generation_id=uuid.uuid4(),
        affected_document_ids=payload.document_ids,
    )
    session.add(job)
    await session.commit()
    generate_wiki.send(str(job.id))
    return job


async def _wiki_job(
    job_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
    *,
    write: bool = False,
) -> WikiUpdateJob:
    job = await session.get(WikiUpdateJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Wiki 任务不存在")
    space = await session.get(WikiSpace, job.space_id)
    if space is None:
        raise HTTPException(status_code=404, detail="Wiki 空间不存在")
    await require_knowledge_base_access(
        session,
        user,
        space.knowledge_base_id,
        write=write,
    )
    return job


@router.get("/jobs/{job_id}", response_model=WikiJobRead)
async def get_wiki_job(
    job_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> WikiUpdateJob:
    return await _wiki_job(job_id, user, session)


@router.post("/jobs/{job_id}/cancel", response_model=WikiJobRead)
async def cancel_wiki_job(
    job_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> WikiUpdateJob:
    job = await _wiki_job(job_id, user, session, write=True)
    if job.status not in {"queued", "running", "quality_check"}:
        raise HTTPException(status_code=409, detail="Wiki 任务已经结束")
    job.cancel_requested_at = datetime.now(UTC)
    await session.commit()
    return job


@router.post(
    "/health/check",
    response_model=WikiHealthJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_wiki_health_check(
    payload: WikiHealthStartRequest,
    user: CurrentUser,
    session: DatabaseSession,
) -> WikiHealthJob:
    space = await _published_space(
        session,
        user,
        payload.knowledge_base_id,
        write=True,
    )
    knowledge_base = await session.get(KnowledgeBase, payload.knowledge_base_id)
    if knowledge_base is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    active = await session.scalar(
        select(WikiHealthJob)
        .where(
            WikiHealthJob.space_id == space.id,
            WikiHealthJob.status.in_(["queued", "running"]),
        )
        .with_for_update()
    )
    if active is not None:
        raise HTTPException(status_code=409, detail="该 Wiki 已有进行中的健康检查")
    try:
        model = await resolve_wiki_health_model(session, knowledge_base)
    except WikiModelConfigurationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    job = WikiHealthJob(
        space_id=space.id,
        model_id=model.id,
        status="queued",
        trigger="manual",
        auto_repair=payload.auto_repair,
    )
    session.add(job)
    await session.commit()
    check_wiki_health.send(str(job.id))
    return job


async def _health_job(
    job_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
    *,
    write: bool = False,
) -> WikiHealthJob:
    job = await session.get(WikiHealthJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Wiki 健康检查不存在")
    space = await session.get(WikiSpace, job.space_id)
    if space is None:
        raise HTTPException(status_code=404, detail="Wiki 空间不存在")
    await require_knowledge_base_access(
        session,
        user,
        space.knowledge_base_id,
        write=write,
    )
    return job


async def _health_job_read(
    job: WikiHealthJob,
    session: DatabaseSession,
) -> WikiHealthJobRead:
    read = WikiHealthJobRead.model_validate(job)
    report = sanitize_wiki_health_report(read.report)
    active_page_ids = {
        str(page_id)
        for page_id in (
            await session.scalars(
                select(WikiPage.id).where(
                    WikiPage.space_id == job.space_id,
                    WikiPage.is_archived.is_(False),
                    WikiPage.current_version_id.is_not(None),
                )
            )
        ).all()
    }
    raw_candidates = report.get("similar_candidates", [])
    if isinstance(raw_candidates, list):
        report["similar_candidates"] = [
            candidate
            for candidate in raw_candidates
            if isinstance(candidate, dict)
            and str(candidate.get("left_page_id", "")) in active_page_ids
            and str(candidate.get("right_page_id", "")) in active_page_ids
        ]
        summary = report.get("summary")
        if isinstance(summary, dict):
            summary["similar_candidates"] = len(report["similar_candidates"])
    allowed_merge_pairs = {
        frozenset(
            {
                str(candidate.get("left_page_id", "")),
                str(candidate.get("right_page_id", "")),
            }
        )
        for candidate in report.get("similar_candidates", [])
        if isinstance(candidate, dict)
    }
    proposed_actions = [
        action
        for action in read.proposed_actions
        if (
            action.get("type") == "merge_pages"
            and frozenset(
                {
                    str(action.get("target_page_id", "")),
                    *(str(page_id) for page_id in action.get("source_page_ids", []) if page_id),
                }
            )
            in allowed_merge_pairs
        )
        or (
            action.get("type") == "add_relation"
            and str(action.get("source_page_id", "")) in active_page_ids
            and str(action.get("target_page_id", "")) in active_page_ids
        )
    ]
    return read.model_copy(
        update={"report": report, "proposed_actions": proposed_actions},
        deep=True,
    )


@router.get("/health/jobs/{job_id}", response_model=WikiHealthJobRead)
async def get_wiki_health_job(
    job_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> WikiHealthJobRead:
    return await _health_job_read(await _health_job(job_id, user, session), session)


@router.get("/{knowledge_base_id}/health/latest", response_model=WikiHealthJobRead)
async def get_latest_wiki_health_job(
    knowledge_base_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> WikiHealthJobRead:
    space = await _published_space(session, user, knowledge_base_id)
    job = await session.scalar(
        select(WikiHealthJob)
        .where(WikiHealthJob.space_id == space.id)
        .order_by(WikiHealthJob.created_at.desc())
    )
    if job is None:
        raise HTTPException(status_code=404, detail="尚未执行 Wiki 健康检查")
    return await _health_job_read(job, session)


@router.get("/{knowledge_base_id}/entity-resolutions")
async def list_wiki_entity_resolutions(
    knowledge_base_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
    decision: str = Query(default="merge", pattern="^(merge|distinct|reverted)$"),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, object]]:
    space = await _published_space(session, user, knowledge_base_id, write=True)
    resolutions = list(
        (
            await session.scalars(
                select(WikiEntityResolution)
                .where(
                    WikiEntityResolution.space_id == space.id,
                    WikiEntityResolution.decision == decision,
                )
                .order_by(WikiEntityResolution.updated_at.desc())
                .limit(limit)
            )
        ).all()
    )
    page_ids = {
        page_id
        for item in resolutions
        for page_id in (item.left_page_id, item.right_page_id, item.canonical_page_id)
        if page_id is not None
    }
    pages = {
        page.id: page
        for page in (await session.scalars(select(WikiPage).where(WikiPage.id.in_(page_ids)))).all()
    }
    return [
        {
            "id": str(item.id),
            "decision": item.decision,
            "left_page_id": str(item.left_page_id),
            "left_title": pages[item.left_page_id].title if item.left_page_id in pages else None,
            "right_page_id": str(item.right_page_id),
            "right_title": pages[item.right_page_id].title if item.right_page_id in pages else None,
            "canonical_page_id": (str(item.canonical_page_id) if item.canonical_page_id else None),
            "canonical_title": (
                pages[item.canonical_page_id].title
                if item.canonical_page_id is not None and item.canonical_page_id in pages
                else None
            ),
            "reason": item.reason,
            "decision_source": item.decision_source,
            "merge_group_id": str(item.merge_group_id) if item.merge_group_id else None,
            "reverted_at": item.reverted_at,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }
        for item in resolutions
    ]


@router.post("/health/jobs/{job_id}/cancel", response_model=WikiHealthJobRead)
async def cancel_wiki_health_job(
    job_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> WikiHealthJob:
    job = await _health_job(job_id, user, session, write=True)
    if job.status not in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="Wiki 健康检查已经结束")
    job.cancel_requested_at = datetime.now(UTC)
    await session.commit()
    return job


@router.post("/{knowledge_base_id}/merge", response_model=WikiPageContent)
async def merge_wiki_nodes(
    knowledge_base_id: uuid.UUID,
    payload: WikiMergePagesRequest,
    user: CurrentUser,
    session: DatabaseSession,
) -> WikiPageContent:
    space = await _published_space(session, user, knowledge_base_id, write=True)
    try:
        target = await merge_wiki_pages(
            session,
            space=space,
            target_page_id=payload.target_page_id,
            source_page_ids=payload.source_page_ids,
            change_summary=payload.change_summary,
            actor_user_id=user.id,
            health_job_id=payload.health_job_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await wiki_read(target.id, user, session)


@router.post("/{knowledge_base_id}/merges/{resolution_id}/undo", response_model=WikiPageContent)
async def undo_wiki_merge(
    knowledge_base_id: uuid.UUID,
    resolution_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> WikiPageContent:
    space = await _published_space(session, user, knowledge_base_id, write=True)
    try:
        target = await undo_wiki_page_merge(
            session,
            space=space,
            resolution_id=resolution_id,
            actor_user_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return await wiki_read(target.id, user, session)


@router.post("/{knowledge_base_id}/similarity-decisions")
async def decide_wiki_similarity_candidate(
    knowledge_base_id: uuid.UUID,
    payload: WikiEntityDecisionRequest,
    user: CurrentUser,
    session: DatabaseSession,
) -> dict[str, object]:
    space = await _published_space(session, user, knowledge_base_id, write=True)
    try:
        resolution = await mark_wiki_pages_distinct(
            session,
            space=space,
            left_page_id=payload.left_page_id,
            right_page_id=payload.right_page_id,
            reason=payload.reason,
            actor_user_id=user.id,
            health_job_id=payload.health_job_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": str(resolution.id), "decision": resolution.decision}


@router.post("/{knowledge_base_id}/relations")
async def add_wiki_relation(
    knowledge_base_id: uuid.UUID,
    payload: WikiAddRelationRequest,
    user: CurrentUser,
    session: DatabaseSession,
) -> dict[str, object]:
    space = await _published_space(session, user, knowledge_base_id, write=True)
    try:
        edge = await add_wiki_page_relation(
            session,
            space=space,
            source_page_id=payload.source_page_id,
            target_page_id=payload.target_page_id,
            relation_type=payload.relation_type,
            evidence=payload.evidence,
            actor_user_id=user.id,
            health_job_id=payload.health_job_id,
            proposal_id=payload.proposal_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": str(edge.id), "status": "created"}


@router.get("/{knowledge_base_id}/log")
async def wiki_activity_log(
    knowledge_base_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    space = await _published_space(session, user, knowledge_base_id)
    updates = list(
        (
            await session.scalars(
                select(WikiUpdateJob)
                .where(WikiUpdateJob.space_id == space.id)
                .order_by(WikiUpdateJob.created_at.desc())
                .limit(limit)
            )
        ).all()
    )
    checks = list(
        (
            await session.scalars(
                select(WikiHealthJob)
                .where(WikiHealthJob.space_id == space.id)
                .order_by(WikiHealthJob.created_at.desc())
                .limit(limit)
            )
        ).all()
    )
    entries: list[dict[str, Any]] = [
        {
            "id": str(item.id),
            "event": "wiki.update",
            "status": item.status,
            "model_id": str(item.model_id) if item.model_id else None,
            "summary": item.change_summary or item.error_summary,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }
        for item in updates
    ]
    entries.extend(
        {
            "id": str(item.id),
            "event": "wiki.health",
            "status": item.status,
            "model_id": str(item.model_id) if item.model_id else None,
            "summary": item.report.get("summary") if item.report else item.error_summary,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }
        for item in checks
    )
    return sorted(entries, key=lambda item: item["created_at"], reverse=True)[:limit]


@router.get("/{knowledge_base_id}/log.md", response_class=PlainTextResponse)
async def wiki_activity_log_markdown(
    knowledge_base_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> str:
    entries = await wiki_activity_log(knowledge_base_id, user, session, limit=200)
    lines = ["# Wiki Log", ""]
    for entry in entries:
        timestamp = entry["updated_at"].isoformat()
        summary = json.dumps(entry["summary"], ensure_ascii=False, default=str)
        lines.append(
            f"- {timestamp} [{entry['event']}] {entry['status']} "
            f"job={entry['id']} model={entry['model_id'] or '未记录'} {summary}"
        )
    return "\n".join(lines)
