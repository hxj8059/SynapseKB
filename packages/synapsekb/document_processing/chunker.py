from __future__ import annotations

import re
from dataclasses import dataclass

import tiktoken

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
PAGE_RE = re.compile(r"<!--\s*page:(\d+)\s*-->")


@dataclass(frozen=True, slots=True)
class TextChunk:
    ordinal: int
    content: str
    section: str | None
    token_count: int
    page_from: int | None = None
    page_to: int | None = None


class HeadingAwareChunker:
    def __init__(self, *, target_tokens: int = 700, overlap_tokens: int = 100) -> None:
        if target_tokens <= overlap_tokens:
            raise ValueError("target_tokens must exceed overlap_tokens")
        self.target_tokens = target_tokens
        self.overlap_tokens = overlap_tokens
        self.encoder = tiktoken.get_encoding("cl100k_base")

    def split(self, markdown: str) -> list[TextChunk]:
        sections = self._sections(markdown)
        chunks: list[TextChunk] = []
        current_page: int | None = None
        for section, content in sections:
            tokens = self.encoder.encode(content)
            step = self.target_tokens - self.overlap_tokens
            for start in range(0, len(tokens), step):
                window = tokens[start : start + self.target_tokens]
                if not window:
                    continue
                text = self.encoder.decode(window).strip()
                page_numbers = [int(value) for value in PAGE_RE.findall(text)]
                page_from = min(page_numbers) if page_numbers else current_page
                page_to = max(page_numbers) if page_numbers else current_page
                if page_numbers:
                    current_page = page_to
                text = PAGE_RE.sub("", text).strip()
                if text:
                    chunks.append(
                        TextChunk(
                            ordinal=len(chunks),
                            content=text,
                            section=section,
                            token_count=len(window),
                            page_from=page_from,
                            page_to=page_to,
                        )
                    )
                if start + self.target_tokens >= len(tokens):
                    break
        return chunks

    @staticmethod
    def _sections(markdown: str) -> list[tuple[str | None, str]]:
        matches = list(HEADING_RE.finditer(markdown))
        if not matches:
            return [(None, markdown)]
        sections: list[tuple[str | None, str]] = []
        if matches[0].start() > 0:
            sections.append((None, markdown[: matches[0].start()]))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
            sections.append((match.group(2).strip(), markdown[match.start() : end]))
        return sections
