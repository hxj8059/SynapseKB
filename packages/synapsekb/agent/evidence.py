"""Build compact, deduplicated evidence without losing source identifiers."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any


def compact_evidence(citations: list[dict[str, Any]], *, max_chars: int) -> str:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    for citation in citations:
        text = str(citation.get("original_text") or "").strip()
        document_id = str(citation.get("document_id") or "")
        key = (document_id, " ".join(text.split()))
        if not text or key in seen:
            continue
        seen.add(key)
        groups[document_id].append(citation)
    # One excerpt per document first, then a second pass: a long document must
    # not crowd every other source out of the final answer context.
    selected: list[str] = []
    used = 0
    snippet_limit = min(1_200, max(200, max_chars // max(len(groups), 1) - 250))
    for offset in range(max((len(group) for group in groups.values()), default=0)):
        for group in groups.values():
            if offset >= len(group):
                continue
            citation = group[offset]
            header = json.dumps(
                {
                    key: citation.get(key)
                    for key in (
                        "citation_number",
                        "document_id",
                        "document_name",
                        "source_time",
                        "section",
                    )
                },
                ensure_ascii=False,
                default=str,
            )
            available = min(snippet_limit, max_chars - used - len(header) - 3)
            if available < 100:
                continue
            excerpt = str(citation["original_text"]).strip()[:available]
            block = f"{header}\n{excerpt}"
            selected.append(block)
            used += len(block) + 2
    return "\n\n".join(selected)
