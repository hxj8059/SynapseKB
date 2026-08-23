from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, and_, exists, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from synapsekb.database.models import KnowledgeBase, KnowledgeBaseMember, User


def require_admin(user: User) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")


def knowledge_base_access_clause(user: User) -> ColumnElement[bool]:
    active = KnowledgeBase.lifecycle_status == "active"
    if user.role == "admin":
        return and_(active, true())
    return and_(
        active,
        or_(
            KnowledgeBase.visibility == "all",
            exists(
                select(KnowledgeBaseMember.user_id).where(
                    and_(
                        KnowledgeBaseMember.knowledge_base_id == KnowledgeBase.id,
                        KnowledgeBaseMember.user_id == user.id,
                    )
                )
            ),
        ),
    )


async def require_knowledge_base_access(
    session: AsyncSession,
    user: User,
    knowledge_base_id: uuid.UUID,
    *,
    write: bool = False,
) -> KnowledgeBase:
    if write and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="知识库写操作需要管理员权限",
        )
    query = select(KnowledgeBase).where(
        KnowledgeBase.id == knowledge_base_id,
        knowledge_base_access_clause(user),
    )
    if write:
        # Hold a shared row lock for the whole write transaction. Knowledge-base
        # deletion takes FOR UPDATE, so it cannot race an upload that has passed
        # authorization but has not committed its object key yet.
        query = query.with_for_update(read=True, key_share=True)
    knowledge_base = await session.scalar(query)
    if knowledge_base is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在或无权访问")
    return knowledge_base
