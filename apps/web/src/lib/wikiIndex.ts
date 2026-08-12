import type { WikiPageSummary } from "./types";

export const WIKI_INDEX_PAGE_SIZE = 12;

export function countWikiPageTypes(
  pages: WikiPageSummary[],
): Array<{ type: string; count: number }> {
  const counts = new Map<string, number>();
  for (const page of pages) {
    const type = page.node_type || "页面";
    counts.set(type, (counts.get(type) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([type, count]) => ({ type, count }))
    .sort((left, right) => right.count - left.count || left.type.localeCompare(right.type));
}

export function filterWikiPages(
  pages: WikiPageSummary[],
  query: string,
  nodeType: string,
): WikiPageSummary[] {
  const normalizedQuery = query.trim().toLocaleLowerCase("zh-CN");
  return pages.filter(
    (page) =>
      (!nodeType || (page.node_type || "页面") === nodeType) &&
      (!normalizedQuery || page.title.toLocaleLowerCase("zh-CN").includes(normalizedQuery)),
  );
}

