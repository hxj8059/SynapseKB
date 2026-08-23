from __future__ import annotations

import ast
import operator
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, and_, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from synapsekb.api.schemas import SearchRequest, TimeFilter
from synapsekb.database.models import (
    Document,
    KnowledgeBase,
    User,
    WikiEdge,
    WikiNode,
    WikiPage,
    WikiPageSource,
    WikiPageVersion,
    WikiSpace,
)
from synapsekb.domain.enums import TimeField
from synapsekb.retrieval.federated import federated_search
from synapsekb.wiki.search import hybrid_wiki_search


@dataclass(slots=True)
class AgentToolContext:
    session: AsyncSession
    user: User
    knowledge_base_ids: list[uuid.UUID]


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "knowledge_search",
            "description": "在授权知识库内执行带过滤条件的混合检索并返回引用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "time_filter": {
                        "type": ["object", "null"],
                        "properties": {
                            "field": {
                                "type": "string",
                                "enum": ["source_time", "created_at", "updated_at"],
                            },
                            "from": {"type": ["string", "null"]},
                            "to": {"type": ["string", "null"]},
                            "include_unknown": {"type": "boolean"},
                        },
                    },
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 30},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "document_read",
            "description": "读取指定授权文档的已解析全文。",
            "parameters": {
                "type": "object",
                "properties": {"document_id": {"type": "string", "format": "uuid"}},
                "required": ["document_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wiki_search",
            "description": (
                "对授权知识库的已发布 Wiki 节点做语义与关键词候选召回并返回相关性排名。"
                "必须先判断候选是否真正相关，再调用 wiki_read；不要先遍历 Wiki 目录。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "time_filter": {"type": ["object", "null"]},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wiki_read",
            "description": "读取 Wiki 页面当前已发布内容。",
            "parameters": {
                "type": "object",
                "properties": {"page_id": {"type": "string", "format": "uuid"}},
                "required": ["page_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wiki_graph_search",
            "description": "搜索 Wiki 图节点及其局部关系。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "time_filter": {"type": ["object", "null"]},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "timeline_search",
            "description": "按结构化时间范围检索知识。必须传 time_filter。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "time_filter": {"type": "object"},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 30},
                },
                "required": ["query", "time_filter"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_periods",
            "description": "分别检索两个独立时间段，禁止把两个时期合并成一次检索。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "period_a": {"type": "object"},
                    "period_b": {"type": "object"},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["query", "period_a", "period_b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "执行不含变量或函数的基础算术。",
            "parameters": {
                "type": "object",
                "properties": {"expression": {"type": "string"}},
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "current_time",
            "description": "返回用户时区当前时间，用于解析相对时间。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


async def _search(
    context: AgentToolContext,
    query: str,
    time_filter: dict[str, Any] | None,
    top_k: int,
    document_ids: list[str] | None = None,
    tag_ids: list[str] | None = None,
) -> dict[str, Any]:
    knowledge_bases = list(
        (
            await context.session.scalars(
                select(KnowledgeBase).where(KnowledgeBase.id.in_(context.knowledge_base_ids))
            )
        ).all()
    )
    request = SearchRequest(
        query=query,
        knowledge_base_ids=context.knowledge_base_ids,
        document_ids=[uuid.UUID(item) for item in document_ids or []],
        tag_ids=[uuid.UUID(item) for item in tag_ids or []],
        time_filter=TimeFilter.model_validate(time_filter) if time_filter else None,
        top_k=min(max(top_k, 1), 30),
    )
    results = await federated_search(
        context.session,
        request,
        knowledge_bases,
    )
    return {
        "count": len(results),
        "time_filter": time_filter,
        "citations": [item.model_dump(mode="json") for item in results],
    }


async def execute_tool(
    name: str,
    arguments: dict[str, Any],
    context: AgentToolContext,
) -> dict[str, Any]:
    if name == "knowledge_search":
        return await _search(
            context,
            arguments["query"],
            arguments.get("time_filter"),
            int(arguments.get("top_k", 12)),
            arguments.get("document_ids"),
            arguments.get("tag_ids"),
        )
    if name == "timeline_search":
        return await _search(
            context,
            arguments["query"],
            arguments["time_filter"],
            int(arguments.get("top_k", 12)),
            arguments.get("document_ids"),
            arguments.get("tag_ids"),
        )
    if name == "compare_periods":
        first = await _search(
            context,
            arguments["query"],
            arguments["period_a"],
            int(arguments.get("top_k", 10)),
            arguments.get("document_ids"),
            arguments.get("tag_ids"),
        )
        second = await _search(
            context,
            arguments["query"],
            arguments["period_b"],
            int(arguments.get("top_k", 10)),
            arguments.get("document_ids"),
            arguments.get("tag_ids"),
        )
        return {"period_a": first, "period_b": second}
    if name == "document_read":
        document = await context.session.get(Document, uuid.UUID(arguments["document_id"]))
        if (
            document is None
            or document.knowledge_base_id not in context.knowledge_base_ids
            or not document.parsed_text_key
        ):
            raise ValueError("文档不存在、未完成解析或不在 Agent 授权范围")
        from synapsekb.storage.factory import create_runtime_storage

        storage = await create_runtime_storage(context.session)
        content = (await storage.read(document.parsed_text_key)).decode("utf-8")
        return {
            "document_id": str(document.id),
            "title": document.title,
            "source_time": document.source_time.isoformat() if document.source_time else None,
            "content": content[:40_000],
            "truncated": len(content) > 40_000,
            "citations": [
                {
                    "citation_number": 1,
                    "chunk_id": None,
                    "document_id": str(document.id),
                    "document_name": document.title,
                    "page_from": None,
                    "page_to": None,
                    "section": "全文读取",
                    "original_text": content[:2_000],
                    "source_time": (
                        document.source_time.isoformat() if document.source_time else None
                    ),
                    "score": 1.0,
                }
            ],
        }
    if name in {"wiki_search", "wiki_read", "wiki_graph_search"}:
        space_ids = select(WikiSpace.id).where(
            WikiSpace.knowledge_base_id.in_(context.knowledge_base_ids),
            WikiSpace.published_version.is_not(None),
        )
        if name == "wiki_search":
            query = arguments["query"]
            time_filter = (
                TimeFilter.model_validate(arguments["time_filter"])
                if arguments.get("time_filter")
                else None
            )
            limit = min(max(int(arguments.get("limit", 10)), 1), 20)
            scope_rows = (
                await context.session.execute(
                    select(KnowledgeBase, WikiSpace)
                    .join(WikiSpace, WikiSpace.knowledge_base_id == KnowledgeBase.id)
                    .where(
                        KnowledgeBase.id.in_(context.knowledge_base_ids),
                        WikiSpace.published_version.is_not(None),
                    )
                )
            ).all()
            ranked_pages: list[dict[str, Any]] = []
            retrievals: list[dict[str, Any]] = []
            for knowledge_base, space in scope_rows:
                result = await hybrid_wiki_search(
                    context.session,
                    knowledge_base=knowledge_base,
                    space=space,
                    query=query,
                    time_clause=_wiki_time_clause(WikiPage, time_filter),
                    limit=limit,
                )
                retrievals.append(
                    {
                        "knowledge_base_id": str(knowledge_base.id),
                        "mode": result.retrieval_mode,
                        "embedding_error": result.embedding_error,
                    }
                )
                ranked_pages.extend(
                    {
                        "id": str(item.page_id),
                        "node_id": str(item.node_id),
                        "knowledge_base_id": str(knowledge_base.id),
                        "title": item.title,
                        "summary": item.summary,
                        "node_type": item.node_type,
                        "source_time": (
                            item.source_time.isoformat() if item.source_time else None
                        ),
                        "relevance_score": item.relevance_score,
                        "semantic_score": item.semantic_score,
                        "keyword_score": item.keyword_score,
                        "matched_by": list(item.matched_by),
                    }
                    for item in result.items
                )
            ranked_pages.sort(
                key=lambda item: (-float(item["relevance_score"]), str(item["title"]))
            )
            pages = ranked_pages[:limit]
            return {
                "pages": [
                    {**page, "rank": rank}
                    for rank, page in enumerate(pages, 1)
                ],
                "retrievals": retrievals,
                "selection_required": (
                    "相关性分数仅用于候选排序；请先确认真正相关的节点，再读取正文和局部关系"
                ),
            }
        if name == "wiki_read":
            page = await context.session.scalar(
                select(WikiPage).where(
                    WikiPage.id == uuid.UUID(arguments["page_id"]),
                    WikiPage.space_id.in_(space_ids),
                )
            )
            if page is None or page.current_version_id is None:
                raise ValueError("Wiki 页面不存在或尚未发布")
            version = await context.session.get(WikiPageVersion, page.current_version_id)
            source_rows = (
                await context.session.execute(
                    select(WikiPageSource, Document.title)
                    .join(Document, Document.id == WikiPageSource.document_id)
                    .where(WikiPageSource.page_version_id == page.current_version_id)
                    .order_by(WikiPageSource.paragraph_key)
                )
            ).all()
            return {
                "id": str(page.id),
                "title": page.title,
                "content": version.content if version else "",
                "source_time": page.source_time.isoformat() if page.source_time else None,
                "citations": [
                    {
                        "citation_number": index,
                        "chunk_id": str(source.chunk_id) if source.chunk_id else None,
                        "document_id": str(source.document_id),
                        "document_name": document_title,
                        "page_from": None,
                        "page_to": None,
                        "section": source.paragraph_key,
                        "original_text": source.evidence_text,
                        "source_time": (
                            source.source_time.isoformat() if source.source_time else None
                        ),
                    }
                    for index, (source, document_title) in enumerate(source_rows, 1)
                ],
            }
        query = arguments["query"]
        time_filter = (
            TimeFilter.model_validate(arguments["time_filter"])
            if arguments.get("time_filter")
            else None
        )
        nodes = (
            await context.session.scalars(
                select(WikiNode)
                .where(
                    WikiNode.space_id.in_(space_ids),
                    WikiNode.label.ilike(f"%{query}%"),
                    _wiki_time_clause(WikiNode, time_filter),
                )
                .limit(min(int(arguments.get("limit", 20)), 50))
            )
        ).all()
        node_ids = [node.id for node in nodes]
        edges = (
            await context.session.scalars(
                select(WikiEdge)
                .where(
                    WikiEdge.space_id.in_(space_ids),
                    _wiki_time_clause(WikiEdge, time_filter),
                    or_(
                        WikiEdge.source_node_id.in_(node_ids),
                        WikiEdge.target_node_id.in_(node_ids),
                    ),
                )
                .limit(100)
            )
        ).all()
        return {
            "nodes": [
                {
                    "id": str(node.id),
                    "type": node.node_type,
                    "label": node.label,
                    "source_time": node.source_time.isoformat() if node.source_time else None,
                }
                for node in nodes
            ],
            "edges": [
                {
                    "id": str(edge.id),
                    "source": str(edge.source_node_id),
                    "target": str(edge.target_node_id),
                    "type": edge.edge_type,
                    "evidence": edge.evidence[:1000],
                    "source_time": edge.source_time.isoformat() if edge.source_time else None,
                }
                for edge in edges
            ],
        }
    if name == "calculator":
        return {"result": _safe_calculate(arguments["expression"])}
    if name == "current_time":
        timezone = ZoneInfo(context.user.timezone or "Asia/Shanghai")
        return {"timezone": str(timezone), "current_time": datetime.now(timezone).isoformat()}
    raise ValueError(f"未知工具: {name}")


def _wiki_time_clause(
    model: type[WikiPage] | type[WikiNode] | type[WikiEdge],
    time_filter: TimeFilter | None,
) -> ColumnElement[bool]:
    if time_filter is None:
        return true()
    column = {
        TimeField.SOURCE_TIME: model.source_time,
        TimeField.CREATED_AT: model.created_at,
        TimeField.UPDATED_AT: model.updated_at,
    }[time_filter.field]
    conditions: list[ColumnElement[bool]] = [column.is_not(None)]
    if time_filter.from_ is not None:
        conditions.append(column >= time_filter.from_)
    if time_filter.to is not None:
        conditions.append(column <= time_filter.to)
    known = and_(*conditions)
    return or_(known, column.is_(None)) if time_filter.include_unknown else known


_OPERATORS: dict[type[ast.operator | ast.unaryop], Callable[..., int | float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_calculate(expression: str) -> int | float:
    if len(expression) > 200:
        raise ValueError("表达式过长")
    tree = ast.parse(expression, mode="eval")

    def evaluate(node: ast.AST) -> int | float:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPERATORS:
            return _OPERATORS[type(node.op)](evaluate(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 10:
                raise ValueError("指数过大")
            return _OPERATORS[type(node.op)](left, right)
        raise ValueError("仅允许基础算术")

    result = evaluate(tree)
    if abs(float(result)) > 1e100:
        raise ValueError("结果过大")
    return result
