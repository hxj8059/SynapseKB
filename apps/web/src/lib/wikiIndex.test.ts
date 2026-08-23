import { describe, expect, it } from "vitest";

import { WIKI_INDEX_PAGE_SIZE, wikiIndexPagePath } from "./wikiIndex";

describe("Wiki index navigation", () => {
  it("builds a bounded server-side page request", () => {
    const path = wikiIndexPagePath("kb-id", 3, "  胜宏科技  ", "个股");
    const url = new URL(path, "http://localhost");

    expect(url.pathname).toBe("/wiki/kb-id/index-page");
    expect(url.searchParams.get("limit")).toBe(String(WIKI_INDEX_PAGE_SIZE));
    expect(url.searchParams.get("offset")).toBe(String(WIKI_INDEX_PAGE_SIZE * 2));
    expect(url.searchParams.get("query")).toBe("胜宏科技");
    expect(url.searchParams.get("node_type")).toBe("个股");
  });

  it("omits empty filters and clamps invalid page numbers", () => {
    const url = new URL(wikiIndexPagePath("kb-id", 0, " ", ""), "http://localhost");
    expect(url.searchParams.get("offset")).toBe("0");
    expect(url.searchParams.has("query")).toBe(false);
    expect(url.searchParams.has("node_type")).toBe(false);
  });
});
