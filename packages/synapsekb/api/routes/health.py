from fastapi import APIRouter, Request
from sqlalchemy import text

from synapsekb.auth.dependencies import DatabaseSession

router = APIRouter()


@router.get("/health", tags=["系统"])
async def health(request: Request, session: DatabaseSession) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    await request.app.state.redis.ping()
    return {"status": "ok"}
