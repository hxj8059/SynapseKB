from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import HTTPException
from synapsekb.api.routes.tokens import delete_token_record
from synapsekb.auth.security import hash_token
from synapsekb.database.models import AuditLog, PersonalAccessToken, User


class _TokenSession:
    def __init__(self, token: PersonalAccessToken | None) -> None:
        self.token = token
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.commit_count = 0

    async def scalar(self, statement: Any) -> PersonalAccessToken | None:
        del statement
        return self.token

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    async def delete(self, instance: Any) -> None:
        self.deleted.append(instance)

    async def commit(self) -> None:
        self.commit_count += 1


def _user() -> User:
    return User(
        id=uuid.uuid4(),
        email="token-owner@example.com",
        display_name="Token owner",
        password_hash="unused",  # noqa: S106
        role="user",
        is_active=True,
        timezone="Asia/Shanghai",
    )


def _token(user: User, *, revoked: bool = False, expired: bool = False) -> PersonalAccessToken:
    now = datetime.now(UTC)
    raw = "skbp_unit-test-token"
    return PersonalAccessToken(
        id=uuid.uuid4(),
        user_id=user.id,
        name="Codex read only",
        token_prefix=raw[:12],
        token_hash=hash_token(raw),
        scopes=["kb:read", "search:read"],
        expires_at=now - timedelta(hours=1) if expired else now + timedelta(days=1),
        created_at=now - timedelta(days=2),
        revoked_at=now - timedelta(hours=2) if revoked else None,
        last_used_at=now - timedelta(hours=3),
    )


@pytest.mark.asyncio
async def test_active_token_must_be_revoked_before_record_deletion() -> None:
    user = _user()
    token = _token(user)
    session = _TokenSession(token)

    with pytest.raises(HTTPException) as caught:
        await delete_token_record(token.id, user, session)  # type: ignore[arg-type]

    assert caught.value.status_code == 409
    assert not session.deleted
    assert session.commit_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["revoked", "expired"])
async def test_inactive_token_record_can_be_deleted_with_audit_snapshot(state: str) -> None:
    user = _user()
    token = _token(user, revoked=state == "revoked", expired=state == "expired")
    session = _TokenSession(token)

    await delete_token_record(token.id, user, session)  # type: ignore[arg-type]

    assert session.deleted == [token]
    assert session.commit_count == 1
    audit = next(item for item in session.added if isinstance(item, AuditLog))
    assert audit.action == "personal_access_token.delete"
    assert audit.resource_id == token.id
    assert audit.metadata_json["name"] == token.name
    assert audit.metadata_json["token_prefix"] == token.token_prefix
    assert token.token_hash not in str(audit.metadata_json)
