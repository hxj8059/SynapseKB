from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from synapsekb.api.schemas import UserCreate, UserRead, UserUpdate
from synapsekb.auth.dependencies import CurrentUser, DatabaseSession
from synapsekb.auth.policy import require_admin
from synapsekb.auth.security import hash_password
from synapsekb.database.models import AuditLog, User

router = APIRouter()


@router.get("", response_model=list[UserRead])
async def list_users(user: CurrentUser, session: DatabaseSession) -> list[User]:
    require_admin(user)
    return list((await session.scalars(select(User).order_by(User.created_at))).all())


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    user: CurrentUser,
    session: DatabaseSession,
) -> User:
    require_admin(user)
    email = payload.email.lower()
    if await session.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=409, detail="邮箱已存在")
    created = User(
        email=email,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
        role=payload.role,
        timezone=payload.timezone,
    )
    session.add(created)
    await session.flush()
    session.add(
        AuditLog(
            actor_user_id=user.id,
            action="user.create",
            resource_type="user",
            resource_id=created.id,
            metadata_json={"role": created.role},
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()
    return created


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    user: CurrentUser,
    session: DatabaseSession,
) -> User:
    require_admin(user)
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if target.id == user.id and payload.is_active is False:
        raise HTTPException(status_code=409, detail="不能停用当前登录管理员")
    if target.id == user.id and payload.role == "user":
        raise HTTPException(status_code=409, detail="不能降低当前登录管理员的角色")
    supplied = payload.model_fields_set
    if "display_name" in supplied and payload.display_name is not None:
        target.display_name = payload.display_name
    if "password" in supplied and payload.password is not None:
        target.password_hash = hash_password(payload.password)
    if "role" in supplied and payload.role is not None:
        target.role = payload.role
    if "is_active" in supplied and payload.is_active is not None:
        target.is_active = payload.is_active
    if "timezone" in supplied and payload.timezone is not None:
        target.timezone = payload.timezone
    session.add(
        AuditLog(
            actor_user_id=user.id,
            action="user.update",
            resource_type="user",
            resource_id=target.id,
            metadata_json={"fields": sorted(supplied)},
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()
    return target
