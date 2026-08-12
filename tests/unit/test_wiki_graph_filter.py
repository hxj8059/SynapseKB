from __future__ import annotations

import uuid

from synapsekb.api.routes.wiki import _strict_graph_subset
from synapsekb.api.schemas import WikiGraphSearchRequest
from synapsekb.database.models import WikiEdge, WikiNode


def _node(node_type: str) -> WikiNode:
    return WikiNode(
        id=uuid.uuid4(),
        space_id=uuid.uuid4(),
        node_type=node_type,
        label=node_type,
    )


def _edge(source: WikiNode, target: WikiNode) -> WikiEdge:
    return WikiEdge(
        id=uuid.uuid4(),
        space_id=source.space_id,
        source_node_id=source.id,
        target_node_id=target.id,
        edge_type="related_to",
        evidence="测试关系",
    )


def test_explicit_node_types_are_a_strict_whitelist() -> None:
    industry = _node("行业")
    product = _node("产品")
    document = _node("document")
    selected_edge = _edge(industry, product)
    document_edge = _edge(industry, document)

    nodes, edges = _strict_graph_subset(
        [industry, product, document],
        [selected_edge, document_edge],
        ["行业", "产品"],
    )

    assert {node.id for node in nodes} == {industry.id, product.id}
    assert [edge.id for edge in edges] == [selected_edge.id]


def test_explicit_empty_node_types_returns_empty_graph() -> None:
    industry = _node("行业")

    nodes, edges = _strict_graph_subset([industry], [], [])

    assert nodes == []
    assert edges == []


def test_omitted_node_types_remains_backward_compatible() -> None:
    omitted = WikiGraphSearchRequest()
    explicit_empty = WikiGraphSearchRequest(node_types=[])

    assert omitted.node_types is None
    assert explicit_empty.node_types == []
    assert omitted.mode == "local"


def test_graph_overview_accepts_a_larger_bounded_limit() -> None:
    overview = WikiGraphSearchRequest(mode="overview", limit=300)

    assert overview.mode == "overview"
    assert overview.limit == 300
