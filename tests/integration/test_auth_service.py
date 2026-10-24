"""AuthService paths that HTTP tests cannot reach directly."""

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.core.clock import FrozenClock
from family_pnl.core.config import Settings
from family_pnl.core.errors import AuthenticationError
from family_pnl.models import User
from family_pnl.repositories.identity import UserRepository
from family_pnl.services.auth import AuthService, EmailTakenError

PASSWORD = "correct horse battery"


async def test_concurrent_registration_with_one_email_is_a_conflict(
    db_session: AsyncSession,
    clock: FrozenClock,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = AuthService(db_session, clock, settings)
    await service.register("anna@example.com", PASSWORD, "Family")

    # The second request passed the existence check before the first one committed.
    async def not_found_yet(self: UserRepository, email: str) -> None:
        return None

    monkeypatch.setattr(UserRepository, "get_by_email", not_found_yet)

    with pytest.raises(EmailTakenError):
        await service.register("anna@example.com", PASSWORD, "Family")


async def test_token_of_a_deleted_user_is_rejected(
    db_session: AsyncSession, clock: FrozenClock, settings: Settings
) -> None:
    service = AuthService(db_session, clock, settings)
    user = await service.register("anna@example.com", PASSWORD, "Family")
    tokens = await service.login("anna@example.com", PASSWORD)
    await db_session.execute(delete(User).where(User.id == user.id))

    with pytest.raises(AuthenticationError):
        await service.authenticate(tokens.access_token)
