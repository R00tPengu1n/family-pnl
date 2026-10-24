import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from family_pnl.domain.currency import Currency
from family_pnl.domain.identity import Role
from family_pnl.models.base import Base
from family_pnl.models.types import checked_enum


class User(Base):
    """A person. Signs in with email and password, through Telegram, or both."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("email IS NOT NULL OR telegram_id IS NOT NULL", name="has_login"),
        CheckConstraint("(email IS NULL) = (password_hash IS NULL)", name="email_with_password"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    # Stored normalised (domain.identity.normalize_email); 320 is the RFC 5321 maximum.
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    # Telegram user ids exceed 2**31, hence BIGINT.
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Household(Base):
    __tablename__ = "households"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    timezone: Mapped[str] = mapped_column(String(64))
    # Budgets and household totals use it; RUB by default (spec), changeable by the owner.
    base_currency: Mapped[Currency] = mapped_column(
        checked_enum(Currency, "base_currency"), default=Currency.RUB, server_default="RUB"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    @classmethod
    def with_owner(
        cls, owner_id: uuid.UUID, *, name: str, timezone: str, now: datetime
    ) -> tuple["Household", "Membership"]:
        """A new, empty household and its owner's membership (not yet in a session)."""
        household = cls(
            id=uuid.uuid4(),
            name=name,
            timezone=timezone,
            base_currency=Currency.RUB,
            created_at=now,
        )
        owner = Membership(
            user_id=owner_id, household_id=household.id, role=Role.OWNER, joined_at=now
        )
        return household, owner


class Membership(Base):
    """A user's place in a household. user_id is the key: one household per user (MVP)."""

    __tablename__ = "memberships"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    # A string with a CHECK constraint, not a native enum: adding a role stays a simple migration.
    role: Mapped[Role] = mapped_column(
        Enum(
            Role,
            name="role",
            native_enum=False,
            create_constraint=True,
            length=16,
            values_callable=lambda roles: [role.value for role in roles],
        )
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RefreshToken(Base):
    """An issued refresh token. Only the SHA-256 digest of the token is stored."""

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # All tokens obtained by rotating one login share a family (ADR-0005, Task 5).
    family_id: Mapped[uuid.UUID] = mapped_column(index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Invite(Base):
    """A one-time code that lets a user join a household. Only its digest is stored."""

    __tablename__ = "invites"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    redeemed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TelegramLinkCode(Base):
    """A one-time code that links a Telegram account to an existing user."""

    __tablename__ = "telegram_link_codes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
