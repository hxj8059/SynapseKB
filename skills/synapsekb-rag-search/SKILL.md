---
name: synapsekb-rag-search
description: Search SynapseKB documents or answer with RAG using explicit knowledge-base, document, tag, and temporal filters while retaining verifiable citations. Use for evidence lookup, source-grounded questions, document discovery, and citation verification.
---

# SynapseKB RAG Search

Apply `synapsekb-shared` first for authentication, permissions, and knowledge-base selection.

## Choose raw search or RAG

Use `knowledge_search` when the user needs:

- matching passages or documents;
- exact evidence for verification;
- coverage inspection before synthesis;
- a source list, page, or section;
- debugging of retrieval filters.

Use `rag_answer` when the user needs:

- a concise answer synthesized from retrieved passages;
- an explanation grounded only in SynapseKB;
- an answer with inline citation numbers.

If the question requires several searches, historical comparison, Wiki graph traversal, or iterative document reading, use a SynapseKB Agent instead.

## Build the request

1. Set `knowledge_base_ids` explicitly.
2. Carry through requested `document_ids` and `tag_ids`.
3. Set a practical `top_k`; start with 20 for discovery and reduce only when the user requests fewer results.
4. Include a structured `time_filter` whenever time is mentioned.
5. Keep the natural-language query focused on the subject. Do not use query text as a substitute for structured filters.

Use this shape:

```json
{
  "query": "查询内容",
  "knowledge_base_ids": ["kb_id"],
  "document_ids": [],
  "tag_ids": [],
  "time_filter": {
    "field": "source_time",
    "from": "2024-01-01T00:00:00+08:00",
    "to": "2024-12-31T23:59:59+08:00",
    "include_unknown": false
  },
  "top_k": 20
}
```

Default the time field to `source_time`. Use `created_at` or `updated_at` only when the user explicitly asks about upload or modification time. Keep `include_unknown=false` for a strict stated period unless the user requests otherwise.

## Evaluate results

1. Check that returned document IDs belong to the requested scope.
2. Check that every known time falls inside the requested interval.
3. Distinguish no matching evidence from a system error.
4. If recall appears too narrow, increase `top_k` or broaden filters transparently; never silently remove a time constraint.
5. Use another raw search to verify a high-impact RAG claim when the returned citations do not clearly support it.

## Present citations

Attach citation numbers to the claims they support. Include:

- document title;
- page and section when present;
- the relevant original passage;
- `source_time`, or an explicit “时间未知” marker;
- a document or preview link when the host exposes one.

Do not cite a document merely because it was retrieved. Cite only evidence used in the answer.

## Handle failure

Follow `synapsekb-shared` for authentication and rate-limit errors. On a model-generation failure after successful retrieval, return the useful raw evidence and state that synthesis failed. Do not fabricate an answer.
