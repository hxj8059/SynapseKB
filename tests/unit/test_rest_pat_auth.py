from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from synapsekb.auth.dependencies import get_current_user, get_document_write_user
from synapsekb.auth.security import create_access_token, hash_token
from synapsekb.database.models import AuditLog, PersonalAccessToken, User


class _PatSession:
    def __init__(self, token: PersonalAccessToken | None, user: User | None) -> None:
        self.token = token
        self.user = user
        self.added: list[Any] = []
        self.commit_count = 0

    async def scalar(self, statement: Any) -> PersonalAccessToken | None:
        del statement
        return self.token

    async def get(self, model: type[Any], object_id: uuid.UUID) -> User | None:
        assert model is User
        if self.user is None or self.user.id != object_id:
            return None
        return self.user

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    async def commit(self) -> None:
        self.commit_count += 1


def _request() -> Request:
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": "/api/v1/documents/upload",
            "raw_path": b"/api/v1/documents/upload",
            "query_string": b"",
            "headers": [],
            "client": ("203.0.113.8", 4242),
            "server": ("synapsekb.example.com", 443),
        }
    )
    request.state.request_id = "rest-pat-test"
    return request


def _user() -> User:
    return User(
        id=uuid.uuid4(),
        email="admin@example.com",
        display_name="管理员",
        password_hash="unused",  # noqa: S106 - authentication hash is irrelevant here
        role="admin",
        is_active=True,
        timezone="Asia/Shanghai",
    )


def _token(raw: str, user: User, scopes: list[str]) -> PersonalAccessToken:
    return PersonalAccessToken(
        id=uuid.uuid4(),
        user_id=user.id,
        name="REST uploader",
        token_prefix=raw[:12],
        token_hash=hash_token(raw),
        scopes=scopes,
        expires_at=datetime.now(UTC) + timedelta(days=1),
        created_at=datetime.now(UTC),
        revoked_at=None,
        last_used_at=None,
    )


@pytest.mark.asyncio
async def test_document_upload_accepts_pat_with_document_write_scope() -> None:
    raw = "skbp_rest-upload-token"
    user = _user()
    token = _token(raw, user, ["document:write"])
    session = _PatSession(token, user)
    request = _request()

    authenticated = await get_document_write_user(
        request,
        HTTPAuthorizationCredentials(scheme="Bearer", credentials=raw),
        session,  # type: ignore[arg-type]
    )

    assert authenticated is user
    assert request.state.auth_type == "personal_access_token"
    assert request.state.personal_access_token_id == token.id
    assert token.last_used_at is not None
    assert session.commit_count == 1
    audit = next(item for item in session.added if isinstance(item, AuditLog))
    assert audit.resource_id == token.id
    assert audit.request_id == "rest-pat-test"
    assert audit.metadata_json == {
        "method": "POST",
        "path": "/api/v1/documents/upload",
        "required_scope": "document:write",
        "outcome": "authorized",
    }
    assert raw not in str(audit.metadata_json)


@pytest.mark.asyncio
async def test_document_upload_rejects_pat_without_document_write_scope() -> None:
    raw = "skbp_read-only-token"
    user = _user()
    token = _token(raw, user, ["document:read"])
    session = _PatSession(token, user)

    with pytest.raises(HTTPException) as caught:
        await get_document_write_user(
            _request(),
            HTTPAuthorizationCredentials(scheme="Bearer", credentials=raw),
            session,  # type: ignore[arg-type]
        )

    assert caught.value.status_code == 403
    assert caught.value.detail == "Token 缺少 Scope: document:write"
    audit = next(item for item in session.added if isinstance(item, AuditLog))
    assert audit.metadata_json["outcome"] == "denied_missing_scope"


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_state", ["revoked", "expired"])
async def test_document_upload_rejects_revoked_or_expired_pat(invalid_state: str) -> None:
    raw = f"skbp_{invalid_state}-token"
    user = _user()
    token = _token(raw, user, ["document:write"])
    if invalid_state == "revoked":
        token.revoked_at = datetime.now(UTC)
    else:
        token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session = _PatSession(token, user)

    with pytest.raises(HTTPException) as caught:
        await get_document_write_user(
            _request(),
            HTTPAuthorizationCredentials(scheme="Bearer", credentials=raw),
            session,  # type: ignore[arg-type]
        )

    assert caught.value.status_code == 401
    assert not session.added


@pytest.mark.asyncio
async def test_document_upload_keeps_jwt_authentication_compatible() -> None:
    user = _user()
    raw, _ = create_access_token(user.id, user.role)
    session = _PatSession(None, user)

    authenticated = await get_document_write_user(
        _request(),
        HTTPAuthorizationCredentials(scheme="Bearer", credentials=raw),
        session,  # type: ignore[arg-type]
    )

    assert authenticated is user
    assert session.commit_count == 0


@pytest.mark.asyncio
async def test_regular_rest_dependency_does_not_accept_pat() -> None:
    raw = "skbp_document-write-token"
    user = _user()
    session = _PatSession(_token(raw, user, ["document:write"]), user)

    with pytest.raises(HTTPException) as caught:
        await get_current_user(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials=raw),
            session,  # type: ignore[arg-type]
        )

    assert caught.value.status_code == 401
    assert not session.added
