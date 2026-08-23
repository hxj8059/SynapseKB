---
name: synapsekb-wiki
description: Navigate private SynapseKB Wiki spaces, read curated pages and sources, search backlinks and local relationship graphs, and inspect time-filtered Wiki history. Use for topic overviews, Wiki navigation, graph relationships, page provenance, and temporal Wiki research.
---

# SynapseKB Wiki

Apply `synapsekb-shared` first for authentication and knowledge-base scope.

## Find and read pages

Use semantic node retrieval as the default entry point. Do not read the first directory page first,
and never traverse directory pages to discover relevant content.

1. Resolve the authorized `knowledge_base_id` with `kb_list` or from the user's explicit choice.
2. Derive one to three concise node-search intents from the question. Prefer stable entities,
   products, companies, technologies, or themes over copying a long question verbatim.
3. Call `wiki_search` directly for each distinct intent and selected knowledge base, normally with
   `limit=8` to `12`. The server searches vectors generated from the node title plus the first 800
   summary characters, fuses exact alias and keyword signals, and returns a relevance ranking.
   When knowledge bases use different Embedding models, compare candidates by meaning and evidence;
   do not assume their numeric scores are calibrated identically.
4. Treat the ranking as candidate recall, not proof of relevance. Compare titles, node types,
   summaries, version qualifiers, and scores, then select only the two to five nodes that actually
   answer the question. Similar names can still be different entities: preserve model or product
   versions such as DeepSeek V3 and DeepSeek V4.
5. Call `wiki_read` only for the selected pages and retain their published sources.
6. For each selected result, use its `node_id` with `wiki_graph_neighbors` to read a bounded
   one-hop neighborhood. Inspect edge evidence, then read a neighboring page only when it adds
   information needed for the answer. Do not expand every candidate or the entire graph.
7. Follow internal page links only when they contribute to the user's question. Distinguish
   AI-generated content, manually protected content, and raw document evidence when exposed.

`wiki_search.retrieval_mode=keyword_fallback` means the query Embedding was unavailable or Wiki
node vectors were not ready. This fallback is automatic. Continue with the ranked exact-alias and
keyword candidates; do not repeatedly retry Embedding. If the fallback returns too few candidates,
try at most two concise synonyms or aliases, then use raw `knowledge_search` and state the fallback.

Use `wiki_index` only when the user explicitly asks to browse the directory, list nodes by type, or
inspect Wiki statistics. It is paginated; follow `next_offset` only for the requested slice. It is
not a relevance-search tool and must not precede `wiki_search` in the normal research workflow.

Wiki pages are private. Do not produce public or unauthenticated Wiki links.

## Inspect relationships

1. Prefer the `node_id` returned by `wiki_search` for an exact graph starting point. Use
   `wiki_graph_search` only when the user asks for a graph-only entity that has no page result.
2. Use `wiki_graph_neighbors` to expand only the relevant local subgraph, one hop at a time.
3. Filter by node or edge type where possible.
4. Pass a structured time range when the user asks about a period.
5. Use `wiki_timeline` to inspect how pages or relationships changed.
6. Read the evidence document before asserting a consequential relationship.

Do not request or attempt to render an entire large graph. Expand from a relevant node in bounded steps.

## Preserve provenance

For each important Wiki claim, retain:

- the Wiki page and version;
- the source document;
- page, section, or passage where available;
- the source relationship or edge evidence;
- `source_time`, or an explicit unknown marker.

A Wiki page is a curated synthesis, not a replacement for primary evidence. Use `knowledge_search` or `document_get` when the user asks to verify the underlying text.

## Apply temporal rules

Default all content and graph time filters to `source_time`. Do not use Wiki publication time as the evidence time. For cross-period graph or page comparison, apply `synapsekb-temporal-research` and query the periods independently.

## Protect administration

Reading published pages and graphs is read-only. Regeneration, manual edits, publishing, rollback, and deletion are writes requiring the appropriate `wiki:admin` scope and explicit user confirmation unless the user already gave a precise instruction for that action.

If generation or publication fails, continue reading the previously published version and report the failed draft or job separately. Never represent an unpublished draft as the current Wiki.

## Handle missing content

- If no Wiki space exists, fall back to raw knowledge search and state that the Wiki has not been generated.
- If a page has no valid sources, label it unverified rather than presenting it as established evidence.
- If a source document was deleted, do not preserve a stale citation.
- On timeout, inspect the existing job before requesting another generation.
