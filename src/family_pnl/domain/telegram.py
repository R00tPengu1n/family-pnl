"""One-time codes that link a Telegram account to an existing user.

The user reads the code in an API client and types it into the bot, so it is short and
avoids look-alike characters (0/O, 1/I/L). 31 symbols over 8 positions give ~8.5e11
combinations; a code lives 10 minutes and works once.
"""

import re
import secrets
from datetime import datetime, timedelta
from enum import StrEnum

from family_pnl.core.errors import ConflictError, ValidationFailedError

LINK_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
LINK_CODE_LENGTH = 8
LINK_CODE_LIFETIME = timedelta(minutes=10)

# Spaces, ASCII hyphens and the Unicode dashes (U+2010..U+2015) phone keyboards insert.
_DASHES = "".join(chr(point) for point in range(0x2010, 0x2016))
_SEPARATORS = re.compile(rf"[\s\-{_DASHES}]")
_VALID = re.compile(f"[{LINK_CODE_ALPHABET}]{{{LINK_CODE_LENGTH}}}")


class LinkCodeInvalidError(ValidationFailedError):
    code = "link_code_invalid"


class CredentialsAlreadySetError(ConflictError):
    code = "credentials_already_set"


class CodePurpose(StrEnum):
    """What a one-time code does when it is used."""

    TELEGRAM = "telegram"  # link this Telegram account to the API user who asked for it
    CREDENTIALS = "credentials"  # give the Telegram user who asked for it an email and password


def new_link_code() -> str:
    return "".join(secrets.choice(LINK_CODE_ALPHABET) for _ in range(LINK_CODE_LENGTH))


def format_link_code(code: str) -> str:
    half = LINK_CODE_LENGTH // 2
    return f"{code[:half]}-{code[half:]}"


def normalize_link_code(typed: str) -> str:
    code = _SEPARATORS.sub("", typed).upper()
    if not _VALID.fullmatch(code):
        raise LinkCodeInvalidError("Link code is invalid or has expired")
    return code


def check_link_code_usable(
    *,
    expires_at: datetime,
    used_at: datetime | None,
    now: datetime,
    purpose: CodePurpose,
    expected: CodePurpose,
) -> None:
    if used_at is not None or now >= expires_at or purpose is not expected:
        raise LinkCodeInvalidError("Link code is invalid or has expired")
