import base64
import os
import uuid

import jwt
from synapsekb.auth.security import (
    create_access_token,
    decode_access_token,
    decrypt_secret,
    encrypt_secret,
    hash_password,
    hash_token,
    issue_opaque_token,
    verify_password,
)
from synapsekb.config import Settings


def test_password_hash_is_salted_and_verifiable() -> None:
    password = "a-secure-test-password"
    first = hash_password(password)
    second = hash_password(password)
    assert first != second
    assert verify_password(password, first)
    assert not verify_password("wrong-password", first)


def test_access_token_requires_expected_type_and_issuer() -> None:
    settings = Settings(jwt_secret="x" * 32)
    user_id = uuid.uuid4()
    token, expires_at = create_access_token(user_id, "user", settings)
    payload = decode_access_token(token, settings)
    assert payload["sub"] == str(user_id)
    assert payload["typ"] == "access"
    assert expires_at.tzinfo is not None

    wrong_issuer = Settings(jwt_secret="y" * 32)
    try:
        decode_access_token(token, wrong_issuer)
    except jwt.InvalidTokenError:
        pass
    else:
        raise AssertionError("token signed with another key must be rejected")


def test_credentials_use_authenticated_encryption() -> None:
    key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    settings = Settings(
        jwt_secret="x" * 32,
        credential_master_key=key,
    )
    encrypted = encrypt_secret("secret-value", context="model:test", settings=settings)
    assert b"secret-value" not in encrypted
    assert decrypt_secret(encrypted, context="model:test", settings=settings) == "secret-value"


def test_opaque_tokens_are_only_persisted_as_hashes() -> None:
    token, digest = issue_opaque_token("skbp")
    assert token.startswith("skbp_")
    assert digest == hash_token(token)
    assert token not in digest
