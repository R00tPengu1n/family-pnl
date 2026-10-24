"""Registration, login and resolving the current user from an access token."""

import uuid
from dataclasses import dataclass

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
from family_pnl.domain.identity import Role, check_password_policy, normalize_email
from family_pnl.models import Household, Membership, RefreshToken, User
from family_pnl.repositories.identity import (
    HouseholdRepository,
    RefreshTokenRepository,
    UserRepository,
)


class EmailTakenError(ConflictError):
    code = "email_taken"


class InvalidCredentialsError(AuthenticationError):
    code = "invalid_credentials"


@dataclass(frozen=True, slots=True)
class CurrentUser:
    id: uuid.UUID
    email: str
    role: Role
    household_id: uuid.UUID
    household_name: str
    household_timezone: str


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int


class AuthService:
    def __init__(self, session: AsyncSession, clock: Clock, settings: Settings) -> None:
        self._session = session
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
        user = User(
            id=uuid.uuid4(), email=email, password_hash=hash_password(password), created_at=now
        )
        household = Household(
            id=uuid.uuid4(),
            name=household_name,
            timezone=self._settings.default_timezone,
            created_at=now,
        )
        membership = Membership(
            user_id=user.id, household_id=household.id, role=Role.OWNER, joined_at=now
        )
        try:
            self._users.add(user)
            self._households.add(household)
            # The rows the membership references are inserted first.
            await self._session.flush()
            self._households.add_member(membership)
            await self._session.commit()
        except IntegrityError as exc:
            # Two registrations with one email raced past the check above.
            await self._session.rollback()
            raise EmailTakenError("An account with this email already exists") from exc
        return _current_user(user, membership, household)

    async def login(self, email: str, password: str) -> TokenPair:
        user = await self._users.get_by_email(normalize_email(email))
        password_hash = user.password_hash if user is not None else None
        if not verify_password_or_dummy(password_hash, password) or user is None:
            raise InvalidCredentialsError("Email or password is incorrect")
        tokens = self._issue_tokens(user.id, family_id=uuid.uuid4())
        await self._session.commit()
        return tokens

    async def authenticate(self, access_token: str) -> CurrentUser:
        user_id = decode_access_token(access_token, secret=self._jwt_secret, now=self._clock.now())
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
        role=membership.role,
        household_id=household.id,
        household_name=household.name,
        household_timezone=household.timezone,
    )
