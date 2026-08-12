---
name: synapsekb-wiki
description: Navigate private SynapseKB Wiki spaces, read curated pages and sources, search backlinks and local relationship graphs, and inspect time-filtered Wiki history. Use for topic overviews, Wiki navigation, graph relationships, page provenance, and temporal Wiki research.
---

# SynapseKB Wiki

Apply `synapsekb-shared` first for authentication and knowledge-base scope.

## Find and read pages

1. Call `wiki_index` to understand the published directory tree for a knowledge base.
2. Call `wiki_search` when the target topic or page is unknown.
3. Call `wiki_read` for the selected page and its published sources.
4. Follow internal page links only when they contribute to the user's question.
5. Distinguish AI-generated content, manually protected content, and raw document evidence when the tool exposes that metadata.

Wiki pages are private. Do not produce public or unauthenticated Wiki links.

## Inspect relationships

1. Use `wiki_graph_search` to locate page, document, or topic nodes.
2. Use `wiki_graph_neighbors` to expand only the relevant local subgraph.
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
