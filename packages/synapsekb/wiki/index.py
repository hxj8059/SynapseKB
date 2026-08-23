from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import Subquery

from synapsekb.database.models import WikiNode, WikiPage, WikiSpace


@dataclass(frozen=True, slots=True)
class WikiIndexItem:
    id: uuid.UUID
    parent_id: uuid.UUID | None
    title: str
    node_type: str
    source_time: datetime | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class WikiIndexTypeCount:
    type: str
    count: int


@dataclass(frozen=True, slots=True)
class WikiIndexResult:
    items: list[WikiIndexItem]
    space_id: uuid.UUID
    total: int
    total_published: int
    limit: int
    offset: int
    published_version: int
    type_counts: list[WikiIndexTypeCount]


def wiki_page_node_types(space_id: uuid.UUID) -> Subquery:
    """Return one deterministic page-node type per page.

    Page nodes are logically one-to-one with Wiki pages. Grouping also keeps the
    directory query safe for databases that contain duplicate legacy rows.
    """

    return (
        select(
            WikiNode.page_id.label("page_id"),
            func.min(WikiNode.node_type).label("node_type"),
        )
        .where(
            WikiNode.space_id == space_id,
            WikiNode.page_id.is_not(None),
        )
        .group_by(WikiNode.page_id)
        .subquery("wiki_page_node_types")
    )


def _literal_title_pattern(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def query_wiki_index(
    session: AsyncSession,
    space: WikiSpace,
    *,
    time_clause: ColumnElement[bool],
    limit: int,
    offset: int,
    query: str | None = None,
    node_type: str | None = None,
) -> WikiIndexResult:
    """Read a lightweight, filtered page of the published Wiki directory."""

    normalized_query = query.strip() if query else ""
    normalized_node_type = node_type.strip() if node_type else ""
    page_nodes = wiki_page_node_types(space.id)
    page_node_type = func.coalesce(page_nodes.c.node_type, literal("页面"))
    published_conditions = (
        WikiPage.space_id == space.id,
        WikiPage.current_version_id.is_not(None),
        WikiPage.is_archived.is_(False),
        time_clause,
    )

    type_rows = (
        await session.execute(
            select(page_node_type.label("node_type"), func.count(WikiPage.id))
            .select_from(WikiPage)
            .outerjoin(page_nodes, page_nodes.c.page_id == WikiPage.id)
            .where(*published_conditions)
            .group_by(page_node_type)
            .order_by(func.count(WikiPage.id).desc(), page_node_type)
        )
    ).all()
    type_counts = [
        WikiIndexTypeCount(type=str(item_type), count=int(count))
        for item_type, count in type_rows
    ]
    total_published = sum(item.count for item in type_counts)

    filtered_conditions: list[ColumnElement[bool]] = list(published_conditions)
    if normalized_query:
        filtered_conditions.append(
            WikiPage.title.ilike(_literal_title_pattern(normalized_query), escape="\\")
        )
    if normalized_node_type:
        filtered_conditions.append(page_node_type == normalized_node_type)

    total = int(
        await session.scalar(
            select(func.count(WikiPage.id))
            .select_from(WikiPage)
            .outerjoin(page_nodes, page_nodes.c.page_id == WikiPage.id)
            .where(*filtered_conditions)
        )
        or 0
    )
    rows = (
        await session.execute(
            select(
                WikiPage.id,
                WikiPage.parent_id,
                WikiPage.title,
                page_node_type.label("node_type"),
                WikiPage.source_time,
                WikiPage.updated_at,
            )
            .select_from(WikiPage)
            .outerjoin(page_nodes, page_nodes.c.page_id == WikiPage.id)
            .where(*filtered_conditions)
            .order_by(WikiPage.sort_order, WikiPage.title, WikiPage.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return WikiIndexResult(
        items=[
            WikiIndexItem(
                id=item_id,
                parent_id=parent_id,
                title=title,
                node_type=str(item_node_type),
                source_time=source_time,
                updated_at=updated_at,
            )
            for item_id, parent_id, title, item_node_type, source_time, updated_at in rows
        ],
        space_id=space.id,
        total=total,
        total_published=total_published,
        limit=limit,
        offset=offset,
        published_version=int(space.published_version or 0),
        type_counts=type_counts,
    )
