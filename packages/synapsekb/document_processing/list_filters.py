from __future__ import annotations

import uuid
from typing import Self

from pydantic import AwareDatetime, BaseModel, Field, model_validator
from sqlalchemy import ColumnElement, and_, exists, or_

from synapsekb.database.models import Document, document_tag_links
from synapsekb.domain.enums import TimeField


class DocumentListFilters(BaseModel):
    knowledge_base_id: uuid.UUID
    status: str | None = None
    name: str | None = Field(default=None, max_length=500)
    tag_ids: list[uuid.UUID] = Field(default_factory=list)
    time_field: TimeField = TimeField.SOURCE_TIME
    from_time: AwareDatetime | None = None
    to_time: AwareDatetime | None = None
    include_unknown: bool = False
    created_from: AwareDatetime | None = None
    created_to: AwareDatetime | None = None
    source_from: AwareDatetime | None = None
    source_to: AwareDatetime | None = None
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0, le=10_000_000)

    @model_validator(mode="after")
    def ordered_ranges(self) -> Self:
        for start, end in (
            (self.from_time, self.to_time),
            (self.created_from, self.created_to),
            (self.source_from, self.source_to),
        ):
            if start and end and end < start:
                raise ValueError("结束时间不能早于开始时间")
        return self

    def clauses(self) -> list[ColumnElement[bool]]:
        clauses = [Document.knowledge_base_id == self.knowledge_base_id]
        if self.status:
            clauses.append(Document.status == self.status)
        if self.name:
            clauses.append(Document.title.icontains(self.name, autoescape=True))
        if self.tag_ids:
            clauses.append(
                exists().where(
                    document_tag_links.c.document_id == Document.id,
                    document_tag_links.c.tag_id.in_(self.tag_ids),
                )
            )
        for column, start, end, unknown in (
            (
                getattr(Document, self.time_field.value),
                self.from_time,
                self.to_time,
                self.include_unknown,
            ),
            (Document.created_at, self.created_from, self.created_to, False),
            (Document.source_time, self.source_from, self.source_to, self.include_unknown),
        ):
            if start is None and end is None:
                continue
            conditions = [column.is_not(None)]
            if start is not None:
                conditions.append(column >= start)
            if end is not None:
                conditions.append(column <= end)
            known = and_(*conditions)
            clauses.append(or_(known, column.is_(None)) if unknown else known)
        return clauses
