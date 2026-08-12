from __future__ import annotations

import re

import jieba

_WHITESPACE = re.compile(r"\s+")


def tokenize_for_postgres(text: str) -> str:
    """Pre-segment Chinese while preserving Latin words for `simple` FTS."""

    normalized = _WHITESPACE.sub(" ", text).strip().lower()
    return " ".join(token.strip() for token in jieba.cut(normalized) if token.strip())
