"""TelegramService races that HTTP tests cannot produce on demand."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.core.clock import FrozenClock
from family_pnl.core.config import Settings
from family_pnl.models import Invite
from family_pnl.repositories.identity import InviteRepository, UserRepository
from family_pnl.services.auth import AuthService
from family_pnl.services.rate_limit import LoginRateLimiter
from family_pnl.services.telegram import TelegramService, TelegramTakenError

TG = 5_000_000_001


async def not_found_yet(self: UserRepository, telegram_id: int) -> None:
    """The other request has not committed yet when this one checks."""
    return


async def test_two_registrations_of_one_telegram_id_racing(
    db_session: AsyncSession,
    clock: FrozenClock,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = TelegramService(db_session, clock, settings)
    await service.register(TG, display_name=None, household_name="Family", invite_code=None)
    monkeypatch.setattr(UserRepository, "get_by_telegram_id", not_found_yet)

    with pytest.raises(TelegramTakenError):
        await service.register(TG, display_name=None, household_name="Family", invite_code=None)


async def test_two_links_of_one_telegram_id_racing(
    db_session: AsyncSession,
    clock: FrozenClock,
    settings: Settings,
    login_limiter: LoginRateLimiter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = TelegramService(db_session, clock, settings)
    await service.register(TG, display_name=None, household_name="Family", invite_code=None)
    auth = AuthService(db_session, clock, settings, login_limiter)
    anna = await auth.register("anna@example.com", "correct horse battery", "Family")
    code = await service.create_link_code(anna)
    monkeypatch.setattr(UserRepository, "get_by_telegram_id", not_found_yet)

    with pytest.raises(TelegramTakenError):
        await service.link(code.code, TG)


async def test_other_integrity_errors_are_not_disguised_as_telegram_taken(
    db_session: AsyncSession,
    clock: FrozenClock,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An invite whose household vanished: the membership's foreign key fails.
    ghost = Invite(
        id=uuid.uuid4(),
        household_id=uuid.uuid4(),
        code_hash="0" * 64,
        created_by=uuid.uuid4(),
        created_at=clock.now(),
        expires_at=clock.now() + timedelta(hours=1),
    )

    async def ghost_invite(self: InviteRepository, code_hash: str) -> Invite:
        return ghost

    monkeypatch.setattr(InviteRepository, "get_for_update", ghost_invite)
    service = TelegramService(db_session, clock, settings)

    with pytest.raises(IntegrityError, match="fk_memberships_household_id_households"):
        await service.register(TG, display_name=None, household_name="Family", invite_code="x")
