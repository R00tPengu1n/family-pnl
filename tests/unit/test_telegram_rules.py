import re
from datetime import UTC, datetime, timedelta

import pytest

from family_pnl.core.errors import ValidationFailedError
from family_pnl.domain.telegram import (
    LINK_CODE_ALPHABET,
    LINK_CODE_LENGTH,
    LINK_CODE_LIFETIME,
    LinkCodeInvalidError,
    check_link_code_usable,
    format_link_code,
    new_link_code,
    normalize_link_code,
)

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def test_link_codes_live_10_minutes() -> None:
    assert timedelta(minutes=10) == LINK_CODE_LIFETIME


def test_alphabet_has_no_easily_confused_characters() -> None:
    assert LINK_CODE_ALPHABET == "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    assert LINK_CODE_LENGTH == 8


def test_new_codes_are_random_and_use_only_the_alphabet() -> None:
    codes = {new_link_code() for _ in range(50)}

    assert len(codes) == 50
    assert all(re.fullmatch(f"[{LINK_CODE_ALPHABET}]{{8}}", code) for code in codes)


def test_codes_are_shown_in_two_groups_of_four() -> None:
    assert format_link_code("K7Q2M9XD") == "K7Q2-M9XD"


@pytest.mark.parametrize(
    "typed", ["K7Q2-M9XD", "k7q2-m9xd", "  K7Q2 M9XD ", "k7q2m9xd", "K7Q2—M9XD"]
)
def test_typed_codes_are_normalised(typed: str) -> None:
    assert normalize_link_code(typed) == "K7Q2M9XD"


@pytest.mark.parametrize("dash", [0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015])
def test_every_unicode_dash_from_hyphen_to_horizontal_bar_is_a_separator(dash: int) -> None:
    assert normalize_link_code(f"K7Q2{chr(dash)}M9XD") == "K7Q2M9XD"


@pytest.mark.parametrize("neighbour", [0x200F, 0x2016])
def test_characters_next_to_the_dash_range_are_not_separators(neighbour: int) -> None:
    # U+200F (right-to-left mark) and U+2016 (double vertical line) bound the range.
    with pytest.raises(LinkCodeInvalidError):
        normalize_link_code(f"K7Q2{chr(neighbour)}M9XD")


@pytest.mark.parametrize("typed", ["", "K7Q2-M9X", "K7Q2-M9XD1", "K7Q2-M9X0", "K7Q2-M9XI"])
def test_codes_of_the_wrong_shape_are_invalid(typed: str) -> None:
    with pytest.raises(LinkCodeInvalidError) as info:
        normalize_link_code(typed)

    assert info.value.code == "link_code_invalid"
    assert info.value.message == "Link code is invalid or has expired"
    assert isinstance(info.value, ValidationFailedError)


def test_fresh_code_is_usable() -> None:
    check_link_code_usable(expires_at=NOW + timedelta(seconds=1), used_at=None, now=NOW)


@pytest.mark.parametrize(
    ("expires_at", "used_at"),
    [
        (NOW, None),
        (NOW - timedelta(seconds=1), None),
        (NOW + timedelta(minutes=5), NOW - timedelta(minutes=1)),
    ],
    ids=["expires-now", "expired", "used"],
)
def test_expired_or_used_code_is_invalid(expires_at: datetime, used_at: datetime | None) -> None:
    with pytest.raises(LinkCodeInvalidError) as info:
        check_link_code_usable(expires_at=expires_at, used_at=used_at, now=NOW)

    assert info.value.message == "Link code is invalid or has expired"
