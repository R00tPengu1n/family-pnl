"""Password hashing (argon2id) and tokens.

Access tokens are short-lived JWTs (HS256). Refresh tokens are opaque random strings; the
database keeps only their SHA-256 digest, so a leaked table cannot be replayed. A digest is
enough for them (unlike passwords) because they carry 256 bits of randomness.
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from functools import lru_cache

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from pydantic import SecretStr

from family_pnl.core.errors import AuthenticationError

ISSUER = "family-pnl"
ACCESS_CLAIM_TYPE = "access"
_ALGORITHM = "HS256"

# argon2-cffi defaults (RFC 9106 low-memory profile): 64 MiB, 3 passes, 4 lanes.
PRODUCTION_HASHER = PasswordHasher()
_hasher = PRODUCTION_HASHER


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return _hasher.hash(secrets.token_urlsafe(16))


def verify_password_or_dummy(password_hash: str | None, password: str) -> bool:
    """Verify against a real hash, or spend the same time on a dummy one and fail.

    Login for an unknown email then takes as long as for a wrong password, so response
    timing does not reveal which emails have accounts.
    """
    if password_hash is None:
        verify_password(_dummy_hash(), password)
        return False
    return verify_password(password_hash, password)


def create_access_token(
    user_id: uuid.UUID, *, secret: SecretStr, now: datetime, ttl: timedelta
) -> str:
    claims = {
        "sub": str(user_id),
        "typ": ACCESS_CLAIM_TYPE,
        "iss": ISSUER,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
    }
    return jwt.encode(claims, secret.get_secret_value(), algorithm=_ALGORITHM)


def decode_access_token(token: str, *, secret: SecretStr, now: datetime) -> uuid.UUID:
    """Return the user id of a valid access token, otherwise raise AuthenticationError."""
    try:
        claims = jwt.decode(
            token,
            secret.get_secret_value(),
            algorithms=[_ALGORITHM],
            issuer=ISSUER,
            # Expiry is checked against the injected clock below, not the system clock.
            options={
                "verify_exp": False,
                "verify_iat": False,
                "require": ["sub", "typ", "iss", "iat", "exp"],
            },
        )
        if claims["typ"] != ACCESS_CLAIM_TYPE or now.timestamp() >= claims["exp"]:
            raise AuthenticationError("Token is invalid or expired")
        return uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise AuthenticationError("Token is invalid or expired") from exc


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_invite_code() -> str:
    # 128 bits; URL-safe, so it fits a Telegram deep link (/start <code>).
    return secrets.token_urlsafe(16)


def hash_invite_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()
