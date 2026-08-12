from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from synapsekb.api.schemas import (
    PersonalAccessTokenCreate,
    PersonalAccessTokenCreated,
    PersonalAccessTokenRead,
)
from synapsekb.auth.dependencies import CurrentUser, DatabaseSession
from synapsekb.auth.security import issue_opaque_token
from synapsekb.database.models import AuditLog, PersonalAccessToken
from synapsekb.domain.enums import DEFAULT_MCP_SCOPES

router = APIRouter()


@router.get("", response_model=list[PersonalAccessTokenRead])
async def list_tokens(
    user: CurrentUser,
    session: DatabaseSession,
) -> list[PersonalAccessToken]:
    return list(
        (
            await session.scalars(
                select(PersonalAccessToken)
                .where(PersonalAccessToken.user_id == user.id)
                .order_by(PersonalAccessToken.created_at.desc())
            )
        ).all()
    )


@router.post(
    "",
    response_model=PersonalAccessTokenCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_token(
    payload: PersonalAccessTokenCreate,
    user: CurrentUser,
    session: DatabaseSession,
) -> PersonalAccessTokenCreated:
    scopes = set(payload.scopes)
    if user.role != "admin" and not scopes.issubset(DEFAULT_MCP_SCOPES):
        raise HTTPException(status_code=403, detail="普通用户只能创建只读默认 Scope")
    if payload.expires_at and payload.expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=422, detail="过期时间必须晚于当前时间")
    raw, token_hash = issue_opaque_token("skbp")
    stored = PersonalAccessToken(
        user_id=user.id,
        name=payload.name,
        token_prefix=raw[:12],
        token_hash=token_hash,
        scopes=sorted(scope.value for scope in scopes),
        expires_at=payload.expires_at,
        created_at=datetime.now(UTC),
    )
    session.add(stored)
    session.add(
        AuditLog(
            actor_user_id=user.id,
            action="personal_access_token.create",
            resource_type="personal_access_token",
            resource_id=stored.id,
            metadata_json={"scopes": stored.scopes},
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()
    return PersonalAccessTokenCreated(
        id=stored.id,
        name=stored.name,
        token=raw,
        scopes=stored.scopes,
        expires_at=stored.expires_at,
    )


@router.delete("/{token_id}", status_code=204)
async def revoke_token(
    token_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> None:
    token = await session.scalar(
        select(PersonalAccessToken).where(
            PersonalAccessToken.id == token_id,
            PersonalAccessToken.user_id == user.id,
        )
    )
    if token is None:
        raise HTTPException(status_code=404, detail="Token 不存在")
    token.revoked_at = datetime.now(UTC)
    session.add(
        AuditLog(
            actor_user_id=user.id,
            action="personal_access_token.revoke",
            resource_type="personal_access_token",
            resource_id=token.id,
            metadata_json={},
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()
