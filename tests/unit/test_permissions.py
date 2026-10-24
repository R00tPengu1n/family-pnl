import uuid
from datetime import UTC, datetime, timedelta

import pytest

from family_pnl.core.errors import ConflictError, PermissionDeniedError, ValidationFailedError
from family_pnl.domain.identity import Role
from family_pnl.domain.permissions import (
    INVITE_LIFETIME,
    AlreadyMemberError,
    HouseholdNotEmptyError,
    InviteInvalidError,
    check_can_join,
    check_invite_usable,
    require_account_editor,
    require_owner,
)

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
HOME = uuid.uuid4()
OTHER = uuid.uuid4()


def test_invites_live_48_hours() -> None:
    assert timedelta(hours=48) == INVITE_LIFETIME


def test_owner_passes_the_owner_check() -> None:
    require_owner(Role.OWNER, "create invites")


def test_member_fails_the_owner_check_with_the_action_in_the_message() -> None:
    with pytest.raises(PermissionDeniedError) as info:
        require_owner(Role.MEMBER, "create invites")

    assert info.value.message == "Only the household owner can create invites"


def test_fresh_invite_is_usable() -> None:
    check_invite_usable(expires_at=NOW + timedelta(seconds=1), redeemed_at=None, now=NOW)


@pytest.mark.parametrize(
    ("expires_at", "redeemed_at"),
    [
        (NOW, None),  # expires exactly now: no longer usable
        (NOW - timedelta(seconds=1), None),
        (NOW + timedelta(hours=1), NOW - timedelta(minutes=5)),
    ],
    ids=["expires-now", "expired", "already-redeemed"],
)
def test_expired_or_redeemed_invite_is_invalid(
    expires_at: datetime, redeemed_at: datetime | None
) -> None:
    with pytest.raises(InviteInvalidError) as info:
        check_invite_usable(expires_at=expires_at, redeemed_at=redeemed_at, now=NOW)

    assert info.value.code == "invite_invalid"
    assert info.value.message == "Invite code is invalid or has expired"
    assert isinstance(info.value, ValidationFailedError)


def test_a_user_alone_in_their_household_can_join_another() -> None:
    check_can_join(
        current_household_id=HOME,
        members_in_current=1,
        invite_household_id=OTHER,
        has_accounts=False,
    )


def test_joining_your_own_household_is_a_conflict() -> None:
    with pytest.raises(AlreadyMemberError) as info:
        check_can_join(
            current_household_id=HOME,
            members_in_current=1,
            invite_household_id=HOME,
            has_accounts=False,
        )

    assert info.value.code == "already_member"
    assert info.value.message == "You are already a member of this household"
    assert isinstance(info.value, ConflictError)


@pytest.mark.parametrize("members", [2, 3])
def test_leaving_a_household_with_other_members_is_a_conflict(members: int) -> None:
    with pytest.raises(HouseholdNotEmptyError) as info:
        check_can_join(
            current_household_id=HOME,
            members_in_current=members,
            invite_household_id=OTHER,
            has_accounts=False,
        )

    assert info.value.code == "household_not_empty"
    assert info.value.message == (
        "You share your household with other members; one household per user is supported"
    )


ANNA = uuid.uuid4()
IVAN = uuid.uuid4()


@pytest.mark.parametrize(
    ("actor", "role", "account_user", "allowed"),
    [
        (ANNA, Role.MEMBER, ANNA, True),  # her own personal account
        (IVAN, Role.MEMBER, ANNA, False),  # another member's personal account
        (IVAN, Role.OWNER, ANNA, True),  # the household owner edits any account
        (ANNA, Role.MEMBER, None, False),  # shared accounts: owner only
        (IVAN, Role.OWNER, None, True),
    ],
    ids=["own", "other-member", "owner-on-personal", "member-on-shared", "owner-on-shared"],
)
def test_who_may_change_an_account(
    actor: uuid.UUID, role: Role, account_user: uuid.UUID | None, allowed: bool
) -> None:
    if allowed:
        require_account_editor(actor_id=actor, role=role, account_user_id=account_user)
    else:
        with pytest.raises(PermissionDeniedError) as info:
            require_account_editor(actor_id=actor, role=role, account_user_id=account_user)
        assert (
            info.value.message == "Only its holder or the household owner can change this account"
        )


def test_only_the_owner_creates_shared_accounts() -> None:
    require_owner(Role.OWNER, "create shared accounts")

    with pytest.raises(PermissionDeniedError) as info:
        require_owner(Role.MEMBER, "create shared accounts")

    assert info.value.message == "Only the household owner can create shared accounts"


def test_a_household_with_accounts_cannot_be_left() -> None:
    with pytest.raises(HouseholdNotEmptyError) as info:
        check_can_join(
            current_household_id=HOME,
            members_in_current=1,
            invite_household_id=OTHER,
            has_accounts=True,
        )

    assert info.value.message == (
        "Your household already has accounts; one household per user is supported"
    )
