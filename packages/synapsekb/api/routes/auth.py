from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from sqlalchemy import select, update

from synapsekb.api.schemas import AccessTokenResponse, LoginRequest, UserRead
from synapsekb.auth.dependencies import CurrentUser, DatabaseSession
from synapsekb.auth.security import (
    create_access_token,
    hash_token,
    issue_opaque_token,
    verify_password,
)
from synapsekb.config import get_settings
from synapsekb.database.models import RefreshToken, User

router = APIRouter()
settings = get_settings()
REFRESH_COOKIE = "synapsekb_refresh"


def _set_refresh_cookie(response: Response, token: str, expires_at: datetime) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        expires=expires_at,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path=f"{settings.api_prefix}/auth",
    )


@router.post("/login", response_model=AccessTokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: DatabaseSession,
) -> AccessTokenResponse:
    email = payload.email.lower()
    user = await session.scalar(select(User).where(User.email == email))
    if (
        user is None
        or not user.is_active
        or not verify_password(payload.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
        )
    access_token, access_expires_at = create_access_token(user.id, user.role)
    refresh_token, token_hash = issue_opaque_token("skbr")
    refresh_expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_token_days)
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            family_id=uuid.uuid4(),
            expires_at=refresh_expires_at,
            created_at=datetime.now(UTC),
            user_agent=request.headers.get("user-agent", "")[:500],
            ip_address=request.client.host if request.client else None,
        )
    )
    await session.commit()
    _set_refresh_cookie(response, refresh_token, refresh_expires_at)
    return AccessTokenResponse(
        access_token=access_token,
        expires_at=access_expires_at,
        user=UserRead.model_validate(user),
    )


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(
    request: Request,
    response: Response,
    session: DatabaseSession,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
) -> AccessTokenResponse:
    if not refresh_token:
        raise HTTPException(status_code=401, detail="缺少刷新令牌")
    now = datetime.now(UTC)
    old_token = await session.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == hash_token(refresh_token))
        .with_for_update()
    )
    if old_token is None or old_token.revoked_at is not None or old_token.expires_at <= now:
        if old_token is not None:
            await session.execute(
                update(RefreshToken)
                .where(RefreshToken.family_id == old_token.family_id)
                .values(revoked_at=now)
            )
            await session.commit()
        raise HTTPException(status_code=401, detail="刷新令牌无效或已过期")
    user = await session.get(User, old_token.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不可用")
    new_raw, new_hash = issue_opaque_token("skbr")
    new_refresh = RefreshToken(
        user_id=user.id,
        token_hash=new_hash,
        family_id=old_token.family_id,
        expires_at=now + timedelta(days=settings.refresh_token_days),
        created_at=now,
        user_agent=request.headers.get("user-agent", "")[:500],
        ip_address=request.client.host if request.client else None,
    )
    session.add(new_refresh)
    await session.flush()
    old_token.revoked_at = now
    old_token.replaced_by_id = new_refresh.id
    await session.commit()
    access_token, expires_at = create_access_token(user.id, user.role)
    _set_refresh_cookie(response, new_raw, new_refresh.expires_at)
    return AccessTokenResponse(
        access_token=access_token,
        expires_at=expires_at,
        user=UserRead.model_validate(user),
    )


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    session: DatabaseSession,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
) -> None:
    if refresh_token:
        token = await session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(refresh_token))
        )
        if token is not None:
            token.revoked_at = datetime.now(UTC)
            await session.commit()
    response.delete_cookie(REFRESH_COOKIE, path=f"{settings.api_prefix}/auth")


@router.get("/me", response_model=UserRead)
async def me(user: CurrentUser) -> User:
    return user
