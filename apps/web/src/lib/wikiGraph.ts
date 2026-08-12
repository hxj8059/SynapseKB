import type { WikiGraph } from "./types";

export function filterWikiGraphByNodeTypes(
  graph: WikiGraph,
  nodeTypes: string[],
): WikiGraph {
  const allowed = new Set(nodeTypes);
  const nodes = graph.nodes.filter((node) => allowed.has(node.type));
  const visibleIds = new Set(nodes.map((node) => node.id));
  const edges = graph.edges.filter(
    (edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target),
  );
  return { ...graph, nodes, edges };
}
