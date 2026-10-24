"""Household accounts: personal (with a holder) or shared."""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.core.clock import Clock
from family_pnl.core.errors import NotFoundError
from family_pnl.domain.currency import Currency
from family_pnl.domain.ledger import AccountType
from family_pnl.domain.permissions import require_account_editor, require_owner
from family_pnl.models import Account
from family_pnl.repositories.ledger import AccountRepository
from family_pnl.services.auth import CurrentUser


class AccountNotFoundError(NotFoundError):
    pass


@dataclass(frozen=True, slots=True)
class AccountChanges:
    name: str | None = None
    type: AccountType | None = None
    archived: bool | None = None


class AccountService:
    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self._session = session
        self._clock = clock
        self._accounts = AccountRepository(session)

    async def create(
        self,
        user: CurrentUser,
        *,
        name: str,
        account_type: AccountType,
        currency: Currency,
        shared: bool,
    ) -> Account:
        if shared:
            require_owner(user.role, "create shared accounts")
        account = Account(
            id=uuid.uuid4(),
            household_id=user.household_id,
            holder_id=None if shared else user.id,
            name=name,
            type=account_type,
            currency=currency,
            archived=False,
            created_by=user.id,
            created_at=self._clock.now(),
        )
        self._accounts.add(account)
        await self._session.commit()
        return account

    async def list(self, user: CurrentUser, *, include_archived: bool) -> list[Account]:
        return await self._accounts.list(user.household_id, include_archived=include_archived)

    async def get(self, user: CurrentUser, account_id: uuid.UUID) -> Account:
        account = await self._accounts.get(user.household_id, account_id)
        if account is None:
            # Missing and foreign look the same (ADR-0004).
            raise AccountNotFoundError("Account not found")
        return account

    async def update(
        self, user: CurrentUser, account_id: uuid.UUID, changes: AccountChanges
    ) -> Account:
        account = await self.get(user, account_id)
        require_account_editor(actor_id=user.id, role=user.role, account_user_id=account.holder_id)
        if changes.name is not None:
            account.name = changes.name
        if changes.type is not None:
            account.type = changes.type
        if changes.archived is not None:
            account.archived = changes.archived
        await self._session.commit()
        return account
