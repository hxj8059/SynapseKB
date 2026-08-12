---
name: synapsekb-temporal-research
description: Perform time-aware SynapseKB research, resolve relative Chinese date expressions, build strict structured filters, inspect timelines, and compare periods with independent retrieval. Use for latest-state questions, historical snapshots, policy changes, trends, or any cross-period comparison.
---

# SynapseKB Temporal Research

Apply `synapsekb-shared` first. Use the user's timezone; default to `Asia/Shanghai`.

## Resolve the requested time

1. Resolve expressions such as “去年”, “上季度”, “最近三个月”, “截至某日”, “以前”, “以后”, and explicit year ranges into concrete timezone-aware start and end instants.
2. Use inclusive calendar boundaries that match the expression.
3. Display the resolved range before or with the result.
4. Default the filter field to `source_time`.
5. Use `created_at` only for upload-time questions and `updated_at` only for SynapseKB modification-time questions.
6. Never substitute either system timestamp for missing `source_time`.

Example execution summary:

```text
已将“去年”解析为 2025-01-01 00:00:00+08:00 至
2025-12-31 23:59:59.999999+08:00，检索字段为 source_time。
```

## Run a single-period investigation

- Use `timeline_search` to retrieve chronologically relevant evidence.
- Use `knowledge_search` when passage relevance matters more than chronological presentation.
- Pass `include_unknown=false` for a strict period.
- Set `include_unknown=true` only when the user deliberately wants undated evidence, and label those results separately.

For “最新版本”, retrieve a sufficiently recent bounded window when one is known, sort or compare by `source_time`, and verify supersession evidence. Do not assume the most recently uploaded document is the newest effective information.

## Compare periods

1. Convert each period into its own complete time filter.
2. Call `compare_periods`, or execute one independent search per period.
3. Never retrieve one broad TopK result set and split it in application text.
4. Compare claims only after confirming each claim has evidence in its own period.
5. Report additions, removals, replacements, unchanged points, and evidence gaps.
6. Cite both sides of every claimed change.

Use a structure like:

```json
{
  "query": "政策要求",
  "knowledge_base_ids": ["kb_id"],
  "periods": [
    {
      "label": "2023",
      "field": "source_time",
      "from": "2023-01-01T00:00:00+08:00",
      "to": "2023-12-31T23:59:59.999999+08:00",
      "include_unknown": false
    },
    {
      "label": "2025",
      "field": "source_time",
      "from": "2025-01-01T00:00:00+08:00",
      "to": "2025-12-31T23:59:59.999999+08:00",
      "include_unknown": false
    }
  ]
}
```

## Inspect Wiki history and graph changes

Use `wiki_timeline` for page or relationship evolution. Use `wiki_graph_search` to find relevant nodes, then request local neighbors for the selected period. Treat edge time as evidence time and show the source document supporting a relationship.

## Present results

State the effective filter field and concrete range. Show `source_time` with every citation. Separate unknown-time evidence and explain that it was excluded from strict comparisons by default.

If one period has no evidence, report the absence; do not turn it into proof that an event did not occur.
