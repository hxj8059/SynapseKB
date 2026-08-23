export const WIKI_INDEX_PAGE_SIZE = 30;

export function wikiIndexPagePath(
  knowledgeBaseId: string,
  page: number,
  query: string,
  nodeType: string,
): string {
  const params = new URLSearchParams({
    limit: String(WIKI_INDEX_PAGE_SIZE),
    offset: String((Math.max(1, page) - 1) * WIKI_INDEX_PAGE_SIZE),
  });
  const normalizedQuery = query.trim();
  const normalizedNodeType = nodeType.trim();
  if (normalizedQuery) params.set("query", normalizedQuery);
  if (normalizedNodeType) params.set("node_type", normalizedNodeType);
  return `/wiki/${knowledgeBaseId}/index-page?${params.toString()}`;
}
