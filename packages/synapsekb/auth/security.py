from __future__ import annotations

import base64
import hashlib
import os
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from synapsekb.config import Settings, get_settings

_password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("密码至少需要 12 个字符")
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_opaque_token(prefix: str = "skb") -> tuple[str, str]:
    raw = f"{prefix}_{secrets.token_urlsafe(32)}"
    return raw, hash_token(raw)


def create_access_token(
    user_id: uuid.UUID,
    role: str,
    settings: Settings | None = None,
) -> tuple[str, datetime]:
    cfg = settings or get_settings()
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=cfg.access_token_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "typ": "access",
        "iss": cfg.jwt_issuer,
        "iat": now,
        "exp": expires_at,
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(
        payload,
        cfg.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    return token, expires_at


def decode_access_token(token: str, settings: Settings | None = None) -> dict[str, Any]:
    cfg = settings or get_settings()
    payload = jwt.decode(
        token,
        cfg.jwt_secret.get_secret_value(),
        algorithms=["HS256"],
        issuer=cfg.jwt_issuer,
        options={"require": ["sub", "exp", "iat", "typ", "jti"]},
    )
    if payload.get("typ") != "access":
        raise jwt.InvalidTokenError("Unexpected token type")
    return payload


def _master_key(settings: Settings) -> bytes:
    encoded = settings.credential_master_key.get_secret_value()
    if not encoded:
        if settings.environment == "production":
            raise RuntimeError("CREDENTIAL_MASTER_KEY is required")
        return hashlib.sha256(settings.jwt_secret.get_secret_value().encode()).digest()
    try:
        key = base64.urlsafe_b64decode(encoded)
    except ValueError as exc:
        raise ValueError("CREDENTIAL_MASTER_KEY must be URL-safe base64") from exc
    if len(key) != 32:
        raise ValueError("CREDENTIAL_MASTER_KEY must decode to exactly 32 bytes")
    return key


def encrypt_secret(value: str, *, context: str, settings: Settings | None = None) -> bytes:
    cfg = settings or get_settings()
    nonce = os.urandom(12)
    cipher = AESGCM(_master_key(cfg))
    encrypted = cipher.encrypt(nonce, value.encode(), context.encode())
    return nonce + encrypted


def decrypt_secret(value: bytes, *, context: str, settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    nonce, encrypted = value[:12], value[12:]
    cipher = AESGCM(_master_key(cfg))
    return cipher.decrypt(nonce, encrypted, context.encode()).decode()
