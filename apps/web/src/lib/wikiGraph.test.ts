import { describe, expect, it } from "vitest";

import type { WikiGraph } from "./types";
import { filterWikiGraphByNodeTypes } from "./wikiGraph";

const graph: WikiGraph = {
  nodes: [
    {
      id: "industry",
      type: "行业",
      label: "人工智能",
      page_id: "page-industry",
      document_id: null,
      source_time: null,
      metadata: {},
    },
    {
      id: "product",
      type: "产品",
      label: "AI 服务器",
      page_id: "page-product",
      document_id: null,
      source_time: null,
      metadata: {},
    },
    {
      id: "document",
      type: "document",
      label: "行业周报",
      page_id: null,
      document_id: "document-id",
      source_time: null,
      metadata: {},
    },
  ],
  edges: [
    {
      id: "industry-product",
      source: "industry",
      target: "product",
      type: "related_to",
      evidence: "",
      source_time: null,
      source_document_id: null,
      source_page_id: null,
    },
    {
      id: "industry-document",
      source: "industry",
      target: "document",
      type: "sourced_from",
      evidence: "",
      source_time: null,
      source_document_id: "document-id",
      source_page_id: null,
    },
  ],
};

describe("filterWikiGraphByNodeTypes", () => {
  it("keeps only explicitly selected node types and their internal edges", () => {
    const filtered = filterWikiGraphByNodeTypes(
      {
        ...graph,
        meta: {
          mode: "overview",
          total_nodes: 100,
          total_edges: 200,
          matched_nodes: 100,
          returned_nodes: 3,
          returned_edges: 2,
          limit: 80,
          truncated: true,
        },
      },
      ["行业", "产品"],
    );

    expect(filtered.nodes.map((node) => node.id)).toEqual(["industry", "product"]);
    expect(filtered.edges.map((edge) => edge.id)).toEqual(["industry-product"]);
    expect(filtered.meta?.total_nodes).toBe(100);
  });

  it("returns an empty graph when no node type is selected", () => {
    expect(filterWikiGraphByNodeTypes(graph, [])).toEqual({ nodes: [], edges: [] });
  });
});
