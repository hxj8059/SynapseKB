from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from synapsekb.auth.security import decode_access_token, hash_token
from synapsekb.database.models import AuditLog, PersonalAccessToken, User
from synapsekb.database.session import get_session
from synapsekb.domain.enums import McpScope

bearer = HTTPBearer(auto_error=False)


def _raw_bearer_token(credentials: HTTPAuthorizationCredentials | None) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少访问令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


async def _jwt_user(raw_token: str, session: AsyncSession) -> User:
    try:
        payload = decode_access_token(raw_token)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="访问令牌无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不可用")
    return user


async def _record_pat_request(
    session: AsyncSession,
    request: Request,
    token: PersonalAccessToken,
    *,
    required_scope: McpScope,
    outcome: str,
) -> None:
    now = datetime.now(UTC)
    if token.last_used_at is None or (now - token.last_used_at).total_seconds() >= 300:
        token.last_used_at = now
    session.add(
        AuditLog(
            actor_user_id=token.user_id,
            action="personal_access_token.api_request",
            resource_type="personal_access_token",
            resource_id=token.id,
            request_id=getattr(request.state, "request_id", None),
            ip_address=getattr(
                request.state,
                "remote_ip",
                request.client.host if request.client else None,
            ),
            metadata_json={
                "method": request.method,
                "path": request.url.path,
                "required_scope": required_scope.value,
                "outcome": outcome,
            },
            created_at=now,
        )
    )
    await session.commit()


async def _pat_user(
    raw_token: str,
    session: AsyncSession,
    request: Request,
    *,
    required_scope: McpScope,
) -> User:
    now = datetime.now(UTC)
    token = await session.scalar(
        select(PersonalAccessToken).where(
            PersonalAccessToken.token_hash == hash_token(raw_token)
        )
    )
    if (
        token is None
        or token.revoked_at is not None
        or (token.expires_at is not None and token.expires_at <= now)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Personal Access Token 无效、已过期或已撤销",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = await session.get(User, token.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不可用")
    if required_scope.value not in token.scopes:
        await _record_pat_request(
            session,
            request,
            token,
            required_scope=required_scope,
            outcome="denied_missing_scope",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Token 缺少 Scope: {required_scope.value}",
        )
    await _record_pat_request(
        session,
        request,
        token,
        required_scope=required_scope,
        outcome="authorized",
    )
    request.state.auth_type = "personal_access_token"
    request.state.personal_access_token_id = token.id
    return user


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    return await _jwt_user(_raw_bearer_token(credentials), session)


async def get_document_write_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    raw_token = _raw_bearer_token(credentials)
    if raw_token.startswith("skbp_"):
        return await _pat_user(
            raw_token,
            session,
            request,
            required_scope=McpScope.DOCUMENT_WRITE,
        )
    return await _jwt_user(raw_token, session)


CurrentUser = Annotated[User, Depends(get_current_user)]
DocumentWriteUser = Annotated[User, Depends(get_document_write_user)]
DatabaseSession = Annotated[AsyncSession, Depends(get_session)]
