import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from family_pnl.models.base import Base


class Notification(Base):
    """An outbox row (ADR-0009): written with the change that caused it, sent by the worker.

    `dedupe_key` is unique, so the same event (a threshold of a category in a month) is
    recorded once however often it is detected.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        Index(
            "ix_notifications_pending",
            "next_attempt_at",
            postgresql_where=text("sent_at IS NULL AND gave_up_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Delivery (ADR-0009): due from this time; after too many failures it is given up.
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    gave_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Users who already got it: a retry after a partial failure skips them.
    delivered_to: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
