from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from synapsekb.api.schemas import CitationRead
from synapsekb.database.models import ProviderModel
from synapsekb.models.provider import DeterministicMockProvider, create_provider

logger = structlog.get_logger()


async def rerank_or_trim(
    session: AsyncSession,
    query: str,
    citations: list[CitationRead],
    top_k: int,
    *,
    model_id: uuid.UUID | None = None,
    allow_default_model: bool = True,
) -> list[CitationRead]:
    if not citations:
        return []
    if model_id is not None:
        model = await session.get(ProviderModel, model_id)
        if model is None or model.kind != "rerank" or not model.is_enabled:
            logger.warning("configured_rerank_model_unavailable", model_id=str(model_id))
            model = None
    elif allow_default_model:
        model = await session.scalar(
            select(ProviderModel)
            .where(
                ProviderModel.kind == "rerank",
                ProviderModel.is_enabled.is_(True),
            )
            .order_by(ProviderModel.created_at)
        )
    else:
        model = None
    if model is None:
        selected = citations[:top_k]
    else:
        provider = create_provider(model)
        if isinstance(provider, DeterministicMockProvider):
            selected = citations[:top_k]
            await provider.close()
        else:
            try:
                ranking = await provider.rerank(
                    query,
                    [item.original_text for item in citations],
                    top_n=min(top_k, len(citations)),
                )
                selected = []
                seen: set[int] = set()
                for index, score in ranking:
                    if index in seen or not 0 <= index < len(citations):
                        continue
                    seen.add(index)
                    selected.append(citations[index].model_copy(update={"score": score}))
                if not selected:
                    selected = citations[:top_k]
            except Exception:
                logger.exception("rerank_failed", model_id=str(model.id))
                selected = citations[:top_k]
            finally:
                await provider.close()
    for citation_number, citation in enumerate(selected, start=1):
        citation.citation_number = citation_number
    return selected
