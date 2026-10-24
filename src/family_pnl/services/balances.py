"""Account balances in the account currency.

Each flow (income, expense, transfer side) is converted to the account currency at the
rate of its own date, exactly; every balance is rounded once at the end. Flows already in
the account currency need no rate at all.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.domain.currency import Currency
from family_pnl.domain.money import Money
from family_pnl.models import Account
from family_pnl.repositories.ledger import AccountRepository, BalanceRepository
from family_pnl.services.auth import CurrentUser
from family_pnl.services.fx import RateService, RatesOnDate


@dataclass(frozen=True, slots=True)
class AccountBalance:
    account: Account
    balance: Money


class BalanceService:
    def __init__(self, session: AsyncSession, rates: RateService) -> None:
        self._accounts = AccountRepository(session)
        self._balances = BalanceRepository(session)
        self._rates = rates

    async def balances(self, user: CurrentUser, *, include_archived: bool) -> list[AccountBalance]:
        accounts = await self._accounts.list(user.household_id, include_archived=include_archived)
        totals = {a.id: Money.zero(a.currency) for a in accounts}
        rates_by_date: dict[date, RatesOnDate] = {}
        for flow in await self._balances.flows(user.household_id):
            if flow.account_id not in totals:
                continue  # an archived account that was not asked for
            total = totals[flow.account_id]
            money = Money(Decimal(flow.amount), Currency(flow.currency))
            if money.currency is not total.currency:
                if flow.operation_date not in rates_by_date:
                    rates_by_date[flow.operation_date] = await self._rates.rates_on(
                        flow.operation_date
                    )
                money = rates_by_date[flow.operation_date].convert(money, total.currency)
            totals[flow.account_id] = total + money
        return [AccountBalance(a, totals[a.id].rounded()) for a in accounts]
