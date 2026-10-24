import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.core.clock import FrozenClock
from family_pnl.core.config import Settings
from family_pnl.domain.ledger import CategoryKind
from family_pnl.repositories.ledger import CategoryRepository
from family_pnl.services.auth import AuthService
from family_pnl.services.categories import CategoryExistsError, CategoryService
from family_pnl.services.rate_limit import LoginRateLimiter


async def test_two_requests_creating_one_name_racing(
    db_session: AsyncSession,
    clock: FrozenClock,
    settings: Settings,
    login_limiter: LoginRateLimiter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    anna = await AuthService(db_session, clock, settings, login_limiter).register(
        "anna@example.com", "correct horse battery", "Family"
    )
    service = CategoryService(db_session, clock)
    await service.create(anna, name="Спорт", kind=CategoryKind.EXPENSE)

    # The other request had not committed yet when this one checked the name.
    async def free(self: CategoryRepository, *args: object) -> bool:
        return False

    monkeypatch.setattr(CategoryRepository, "name_taken", free)

    with pytest.raises(CategoryExistsError):
        await service.create(anna, name="спорт", kind=CategoryKind.EXPENSE)
