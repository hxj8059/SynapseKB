import { describe, expect, it } from "vitest";

import type { WikiPageSummary } from "./types";
import { countWikiPageTypes, filterWikiPages } from "./wikiIndex";

function page(title: string, nodeType: string): WikiPageSummary {
  return {
    id: title,
    space_id: "space",
    parent_id: null,
    slug: title,
    title,
    summary: "",
    sort_order: 0,
    source_time: null,
    current_version_id: "version",
    is_archived: false,
    merged_into_page_id: null,
    node_type: nodeType,
    created_at: "2026-08-05T00:00:00Z",
    updated_at: "2026-08-05T00:00:00Z",
  };
}

describe("Wiki index navigation", () => {
  const pages = [page("PCB", "产业主题"), page("沪电股份", "个股"), page("胜宏科技", "个股")];

  it("counts each node type", () => {
    expect(countWikiPageTypes(pages)).toEqual([
      { type: "个股", count: 2 },
      { type: "产业主题", count: 1 },
    ]);
  });

  it("filters by node type and title", () => {
    expect(filterWikiPages(pages, "科技", "个股").map((item) => item.title)).toEqual([
      "胜宏科技",
    ]);
  });
});

