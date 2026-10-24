import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from pydantic import SecretStr

from family_pnl.core.errors import AuthenticationError
from family_pnl.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
    verify_password_or_dummy,
)

SECRET = SecretStr("test-secret-that-is-long-enough-for-hs256")
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
TTL = timedelta(minutes=15)


def test_password_hash_verifies_and_rejects_a_wrong_password() -> None:
    hashed = hash_password("correct horse battery")

    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "correct horse battery") is True
    assert verify_password(hashed, "wrong horse battery") is False


def test_same_password_gets_a_different_salt_each_time() -> None:
    assert hash_password("correct horse battery") != hash_password("correct horse battery")


def test_malformed_hash_is_a_failed_verification_not_a_crash() -> None:
    assert verify_password("not-an-argon2-hash", "whatever") is False


def test_dummy_verification_without_a_hash_always_fails() -> None:
    # Unknown email: still spend the hashing time, so timing does not reveal accounts.
    assert verify_password_or_dummy(None, "any password at all") is False


def test_access_token_round_trip_returns_the_user_id() -> None:
    user_id = uuid.uuid4()
    token = create_access_token(user_id, secret=SECRET, now=NOW, ttl=TTL)

    assert (
        decode_access_token(token, secret=SECRET, now=NOW + TTL - timedelta(seconds=1)) == user_id
    )


def test_expired_access_token_is_rejected() -> None:
    token = create_access_token(uuid.uuid4(), secret=SECRET, now=NOW, ttl=TTL)

    with pytest.raises(AuthenticationError):
        decode_access_token(token, secret=SECRET, now=NOW + TTL)


def test_token_signed_with_another_secret_is_rejected() -> None:
    token = create_access_token(uuid.uuid4(), secret=SECRET, now=NOW, ttl=TTL)

    with pytest.raises(AuthenticationError):
        decode_access_token(token, secret=SecretStr("another-secret-of-sufficient-len"), now=NOW)


def test_tampered_token_is_rejected() -> None:
    token = create_access_token(uuid.uuid4(), secret=SECRET, now=NOW, ttl=TTL)
    header, payload, signature = token.split(".")
    tampered = f"{header}.{payload}x.{signature}"

    with pytest.raises(AuthenticationError):
        decode_access_token(tampered, secret=SECRET, now=NOW)


def test_unsigned_token_is_rejected() -> None:
    claims = {"sub": str(uuid.uuid4()), "iat": NOW, "exp": NOW + TTL, "iss": "family-pnl"}
    unsigned = jwt.encode({**claims, "typ": "access"}, key=None, algorithm="none")

    with pytest.raises(AuthenticationError):
        decode_access_token(unsigned, secret=SECRET, now=NOW)


def test_token_of_another_type_is_rejected() -> None:
    claims = {
        "sub": str(uuid.uuid4()),
        "iat": NOW,
        "exp": NOW + TTL,
        "iss": "family-pnl",
        "typ": "telegram-link",
    }
    other = jwt.encode(claims, SECRET.get_secret_value(), algorithm="HS256")

    with pytest.raises(AuthenticationError):
        decode_access_token(other, secret=SECRET, now=NOW)


def test_refresh_tokens_are_random_and_stored_only_as_a_digest() -> None:
    first, second = new_refresh_token(), new_refresh_token()

    assert first != second
    assert len(first) >= 43  # 32 random bytes, URL-safe base64
    assert hash_refresh_token(first) == hash_refresh_token(first)
    assert hash_refresh_token(first) != first
