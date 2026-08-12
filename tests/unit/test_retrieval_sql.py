import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.dialects import postgresql
from synapsekb.api.schemas import SearchRequest
from synapsekb.retrieval.service import HybridRetriever


def compile_query(field: str) -> str:
    payload = SearchRequest.model_validate(
        {
            "query": "政策",
            "knowledge_base_ids": [str(uuid.uuid4())],
            "time_filter": {
                "field": field,
                "from": datetime(2024, 1, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
                "to": datetime(2024, 12, 31, tzinfo=ZoneInfo("Asia/Shanghai")),
                "include_unknown": False,
            },
            "top_k": 20,
        }
    )
    statement = HybridRetriever().build_query(payload, [0.0] * 1536)
    return str(
        statement.compile(
            dialect=postgresql.dialect(),  # type: ignore[no-untyped-call]
            compile_kwargs={"literal_binds": False},
        )
    )


def test_time_filter_is_inside_both_candidate_ctes() -> None:
    sql = compile_query("source_time")
    keyword_cte, vector_cte = sql.split("vector AS", maxsplit=1)
    assert "chunks.source_time >=" in keyword_cte
    assert "chunks.source_time >=" in vector_cte
    assert "chunks.source_time IS NOT NULL" in keyword_cte
    assert "chunks.source_time IS NOT NULL" in vector_cte


def test_created_and_updated_time_fields_are_independent() -> None:
    assert "chunks.created_at >=" in compile_query("created_at")
    assert "chunks.updated_at >=" in compile_query("updated_at")
