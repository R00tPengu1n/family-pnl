"""Telegram accounts: registration from the bot, linking codes and bot tokens (ADR-0007)."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import NoReturn

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.core.clock import Clock
from family_pnl.core.config import Settings
from family_pnl.core.errors import ConflictError, NotFoundError
from family_pnl.core.security import create_access_token, hash_invite_code
from family_pnl.domain.identity import Role
from family_pnl.domain.permissions import InviteInvalidError, check_invite_usable
from family_pnl.domain.telegram import (
    LINK_CODE_LIFETIME,
    LinkCodeInvalidError,
    check_link_code_usable,
    format_link_code,
    new_link_code,
    normalize_link_code,
)
from family_pnl.models import Category, Household, Membership, TelegramLinkCode, User
from family_pnl.repositories.identity import (
    HouseholdRepository,
    InviteRepository,
    TelegramLinkCodeRepository,
    UserRepository,
)
from family_pnl.services.auth import CurrentUser


class TelegramTakenError(ConflictError):
    code = "telegram_taken"


class TelegramAlreadyLinkedError(ConflictError):
    code = "telegram_already_linked"


class TelegramNotRegisteredError(NotFoundError):
    code = "telegram_not_registered"


@dataclass(frozen=True, slots=True)
class IssuedLinkCode:
    code: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class AccessToken:
    access_token: str
    expires_in: int


class TelegramService:
    def __init__(self, session: AsyncSession, clock: Clock, settings: Settings) -> None:
        self._session = session
        self._clock = clock
        self._settings = settings
        self._users = UserRepository(session)
        self._households = HouseholdRepository(session)
        self._invites = InviteRepository(session)
        self._link_codes = TelegramLinkCodeRepository(session)

    async def create_link_code(self, user: CurrentUser) -> IssuedLinkCode:
        now = self._clock.now()
        code = new_link_code()
        stored = TelegramLinkCode(
            id=uuid.uuid4(),
            user_id=user.id,
            code_hash=hash_invite_code(code),
            created_at=now,
            expires_at=now + LINK_CODE_LIFETIME,
        )
        self._link_codes.add(stored)
        await self._session.commit()
        return IssuedLinkCode(code=format_link_code(code), expires_at=stored.expires_at)

    async def link(self, typed_code: str, telegram_id: int) -> uuid.UUID:
        """Bind a Telegram account to the user who requested the code; return the user id."""
        now = self._clock.now()
        code = await self._link_codes.get_for_update(
            hash_invite_code(normalize_link_code(typed_code))
        )
        if code is None:
            raise LinkCodeInvalidError("Link code is invalid or has expired")
        check_link_code_usable(expires_at=code.expires_at, used_at=code.used_at, now=now)
        user = await self._users.lock(code.user_id)
        if user.telegram_id is not None:
            raise TelegramAlreadyLinkedError("Another Telegram account is already linked")
        if await self._users.get_by_telegram_id(telegram_id) is not None:
            raise TelegramTakenError("This Telegram account belongs to another user")
        user.telegram_id = telegram_id
        code.used_at = now
        await self._commit_or_taken()
        return user.id

    async def register(
        self,
        telegram_id: int,
        *,
        display_name: str | None,
        household_name: str,
        invite_code: str | None,
    ) -> uuid.UUID:
        """Create a Telegram-only user: owner of a new household, or a member through an invite.

        The invite is validated before anything is added: a bad invite creates no user.
        """
        if await self._users.get_by_telegram_id(telegram_id) is not None:
            raise TelegramTakenError("This Telegram account is already registered")
        now = self._clock.now()
        invite = None
        if invite_code is not None:
            invite = await self._invites.get_for_update(hash_invite_code(invite_code))
            if invite is None:
                raise InviteInvalidError("Invite code is invalid or has expired")
            check_invite_usable(
                expires_at=invite.expires_at, redeemed_at=invite.redeemed_at, now=now
            )

        user = User(
            id=uuid.uuid4(), telegram_id=telegram_id, display_name=display_name, created_at=now
        )
        self._users.add(user)
        if invite is None:
            household, membership = Household.with_owner(
                user.id, name=household_name, timezone=self._settings.default_timezone, now=now
            )
            self._households.add(household)
        else:
            membership = Membership(
                user_id=user.id, household_id=invite.household_id, role=Role.MEMBER, joined_at=now
            )
        try:
            # Rows that reference the new user (membership, invite) are written after it.
            await self._session.flush()
            self._households.add_member(membership)
            if invite is None:
                self._session.add_all(Category.defaults_for(membership.household_id, now))
            if invite is not None:
                invite.redeemed_by = user.id
                invite.redeemed_at = now
            await self._session.commit()
        except IntegrityError as exc:
            await self._reraise_integrity_error(exc)
        return user.id

    async def issue_access_token(self, telegram_id: int) -> AccessToken:
        user = await self._users.get_by_telegram_id(telegram_id)
        if user is None:
            raise TelegramNotRegisteredError("No account is registered for this Telegram user")
        ttl = self._settings.access_token_ttl
        token = create_access_token(
            user.id, secret=self._settings.jwt_secret, now=self._clock.now(), ttl=ttl
        )
        return AccessToken(access_token=token, expires_in=int(ttl.total_seconds()))

    async def _commit_or_taken(self) -> None:
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._reraise_integrity_error(exc)

    async def _reraise_integrity_error(self, exc: IntegrityError) -> NoReturn:
        """A lost race for one Telegram id is a 409; any other violation stays a bug."""
        await self._session.rollback()
        if "uq_users_telegram_id" in str(exc.orig):
            raise TelegramTakenError("This Telegram account belongs to another user") from exc
        raise exc
