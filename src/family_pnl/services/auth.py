"""Registration, login and resolving the current user from an access token."""

import asyncio
import uuid
from dataclasses import dataclass

import structlog
from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.core.clock import Clock
from family_pnl.core.config import Settings
from family_pnl.core.errors import AuthenticationError, ConflictError
from family_pnl.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password_or_dummy,
)
from family_pnl.domain.currency import Currency
from family_pnl.domain.identity import Role, check_password_policy, normalize_email
from family_pnl.models import Category, Household, Membership, RefreshToken, User
from family_pnl.repositories.identity import (
    HouseholdRepository,
    RefreshTokenRepository,
    UserRepository,
)
from family_pnl.services.rate_limit import LoginRateLimiter


class EmailTakenError(ConflictError):
    code = "email_taken"


class InvalidCredentialsError(AuthenticationError):
    code = "invalid_credentials"


class InvalidRefreshTokenError(AuthenticationError):
    code = "invalid_refresh_token"


logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class CurrentUser:
    id: uuid.UUID
    email: str | None
    display_name: str | None
    telegram_linked: bool
    role: Role
    household_id: uuid.UUID
    household_name: str
    household_timezone: str
    household_base_currency: Currency
    display_currency_pref: Currency | None = None
    input_currency_pref: Currency | None = None

    @property
    def display_currency(self) -> Currency:
        return self.display_currency_pref or self.household_base_currency

    @property
    def input_currency(self) -> Currency:
        return self.input_currency_pref or self.household_base_currency


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int


class AuthService:
    def __init__(
        self,
        session: AsyncSession,
        clock: Clock,
        settings: Settings,
        login_limiter: LoginRateLimiter,
    ) -> None:
        self._session = session
        self._login_limiter = login_limiter
        self._clock = clock
        self._settings = settings
        self._users = UserRepository(session)
        self._households = HouseholdRepository(session)
        self._refresh_tokens = RefreshTokenRepository(session)

    async def register(self, email: str, password: str, household_name: str) -> CurrentUser:
        """Create a user who owns a new, empty household."""
        email = normalize_email(email)
        check_password_policy(password, email=email)
        if await self._users.get_by_email(email) is not None:
            raise EmailTakenError("An account with this email already exists")

        now = self._clock.now()
        # argon2 takes tens of milliseconds of CPU: off the event loop, other requests go on.
        password_hash = await asyncio.to_thread(hash_password, password)
        user = User(id=uuid.uuid4(), email=email, password_hash=password_hash, created_at=now)
        household, membership = Household.with_owner(
            user.id, name=household_name, timezone=self._settings.default_timezone, now=now
        )
        try:
            self._users.add(user)
            self._households.add(household)
            # The rows the membership references are inserted first.
            await self._session.flush()
            self._households.add_member(membership)
            self._session.add_all(Category.defaults_for(household.id, now))
            await self._session.commit()
        except IntegrityError as exc:
            # Two registrations with one email raced past the check above.
            await self._session.rollback()
            raise EmailTakenError("An account with this email already exists") from exc
        return _current_user(user, membership, household)

    async def login(self, email: str, password: str, *, ip: str) -> TokenPair:
        # Counted before hashing: refused attempts cost no argon2 work.
        await self._login_limiter.reserve(email, ip)
        user = await self._users.get_by_email(normalize_email(email))
        password_hash = user.password_hash if user is not None else None
        valid = await asyncio.to_thread(verify_password_or_dummy, password_hash, password)
        if not valid or user is None:
            raise InvalidCredentialsError("Email or password is incorrect")
        await self._login_limiter.succeeded(email, ip)
        tokens = self._issue_tokens(user.id, family_id=uuid.uuid4())
        await self._session.commit()
        return tokens

    async def refresh(self, refresh_token: str) -> TokenPair:
        """Rotate a refresh token: revoke it and issue a new pair in the same family.

        A token that was already rotated or revoked is a replay, most likely of a stolen
        token: the whole family is revoked, ending the session for both parties (ADR-0005).
        """
        now = self._clock.now()
        stored = await self._refresh_tokens.get_for_update(hash_refresh_token(refresh_token))
        if stored is None or stored.expires_at <= now:
            raise InvalidRefreshTokenError("Refresh token is invalid or expired")
        if stored.revoked_at is not None:
            await self._refresh_tokens.revoke_family(stored.family_id, now)
            await self._session.commit()
            logger.warning(
                "refresh_token_reuse", user_id=str(stored.user_id), family_id=str(stored.family_id)
            )
            raise InvalidRefreshTokenError("Refresh token is invalid or expired")
        stored.revoked_at = now
        tokens = self._issue_tokens(stored.user_id, family_id=stored.family_id)
        await self._session.commit()
        return tokens

    async def logout(self, refresh_token: str) -> None:
        """End the login session the token belongs to. Unknown tokens are ignored."""
        stored = await self._refresh_tokens.get_for_update(hash_refresh_token(refresh_token))
        if stored is not None:
            await self._refresh_tokens.revoke_family(stored.family_id, self._clock.now())
        await self._session.commit()

    async def authenticate(self, access_token: str) -> CurrentUser:
        user_id = decode_access_token(access_token, secret=self._jwt_secret, now=self._clock.now())
        return await self.current_user(user_id)

    async def current_user(self, user_id: uuid.UUID) -> CurrentUser:
        """The user with their current membership, read fresh from the database."""
        user = await self._users.get(user_id)
        found = await self._households.get_membership(user_id)
        if user is None or found is None:
            # A valid signature for a user who no longer exists.
            raise AuthenticationError("Token is invalid or expired")
        membership, household = found
        return _current_user(user, membership, household)

    def _issue_tokens(self, user_id: uuid.UUID, *, family_id: uuid.UUID) -> TokenPair:
        now = self._clock.now()
        refresh_token = new_refresh_token()
        self._refresh_tokens.add(
            RefreshToken(
                id=uuid.uuid4(),
                user_id=user_id,
                family_id=family_id,
                token_hash=hash_refresh_token(refresh_token),
                issued_at=now,
                expires_at=now + self._settings.refresh_token_ttl,
            )
        )
        access_ttl = self._settings.access_token_ttl
        return TokenPair(
            access_token=create_access_token(
                user_id, secret=self._jwt_secret, now=now, ttl=access_ttl
            ),
            refresh_token=refresh_token,
            expires_in=int(access_ttl.total_seconds()),
        )

    @property
    def _jwt_secret(self) -> SecretStr:
        return self._settings.jwt_secret


def _current_user(user: User, membership: Membership, household: Household) -> CurrentUser:
    return CurrentUser(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        telegram_linked=user.telegram_id is not None,
        role=membership.role,
        household_id=household.id,
        household_name=household.name,
        household_timezone=household.timezone,
        household_base_currency=household.base_currency,
        display_currency_pref=user.display_currency,
        input_currency_pref=user.input_currency,
    )
