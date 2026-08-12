from __future__ import annotations

from sqlalchemy import ColumnElement, and_, or_, true

from synapsekb.api.schemas import TimeFilter
from synapsekb.database.models import Chunk
from synapsekb.domain.enums import TimeField

TIME_COLUMNS = {
    TimeField.SOURCE_TIME: Chunk.source_time,
    TimeField.CREATED_AT: Chunk.created_at,
    TimeField.UPDATED_AT: Chunk.updated_at,
}


def chunk_time_clause(time_filter: TimeFilter | None) -> ColumnElement[bool]:
    if time_filter is None:
        return true()
    column = TIME_COLUMNS[time_filter.field]
    clauses: list[ColumnElement[bool]] = []
    if time_filter.from_ is not None:
        clauses.append(column >= time_filter.from_)
    if time_filter.to is not None:
        clauses.append(column <= time_filter.to)
    known_clause: ColumnElement[bool] = and_(*clauses) if clauses else column.is_not(None)
    if time_filter.include_unknown:
        return or_(known_clause, column.is_(None))
    return and_(column.is_not(None), known_clause)
