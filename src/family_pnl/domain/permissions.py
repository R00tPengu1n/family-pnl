"""Who may do what inside a household, and when an invite can be used."""

import uuid
from datetime import datetime, timedelta

from family_pnl.core.errors import ConflictError, PermissionDeniedError, ValidationFailedError
from family_pnl.domain.identity import Role

INVITE_LIFETIME = timedelta(hours=48)


class InviteInvalidError(ValidationFailedError):
    code = "invite_invalid"


class AlreadyMemberError(ConflictError):
    code = "already_member"


class HouseholdNotEmptyError(ConflictError):
    code = "household_not_empty"


def require_owner(role: Role, action: str) -> None:
    if role is not Role.OWNER:
        raise PermissionDeniedError(f"Only the household owner can {action}")


def check_invite_usable(
    *, expires_at: datetime, redeemed_at: datetime | None, now: datetime
) -> None:
    # One message for every reason, so a code reveals nothing about its history.
    if redeemed_at is not None or now >= expires_at:
        raise InviteInvalidError("Invite code is invalid or has expired")


def check_can_join(
    *, current_household_id: uuid.UUID, members_in_current: int, invite_household_id: uuid.UUID
) -> None:
    """One household per user (MVP): only a user alone in their household may move."""
    if current_household_id == invite_household_id:
        raise AlreadyMemberError("You are already a member of this household")
    if members_in_current > 1:
        raise HouseholdNotEmptyError(
            "You share your household with other members; one household per user is supported"
        )
