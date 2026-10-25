"""The notification outbox (ADR-0009)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.models import Notification


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_once(
        self,
        *,
        notification_id: uuid.UUID,
        household_id: uuid.UUID,
        kind: str,
        dedupe_key: str,
        payload: dict[str, Any],
        created_at: datetime,
    ) -> None:
        """Record an event unless one with the same key already exists."""
        await self._session.execute(
            insert(Notification)
            .values(
                id=notification_id,
                household_id=household_id,
                kind=kind,
                dedupe_key=dedupe_key,
                payload=payload,
                created_at=created_at,
                attempts=0,
                next_attempt_at=created_at,
            )
            .on_conflict_do_nothing(index_elements=["dedupe_key"])
        )

    async def lock(self, notification_id: uuid.UUID) -> Notification:
        """One notification, locked: to record a failure after a rollback."""
        return await self._session.get_one(Notification, notification_id, with_for_update=True)

    async def lock_next_due(self, now: datetime) -> Notification | None:
        """The oldest notification due by `now`, locked; rows other workers hold are skipped."""
        return await self._session.scalar(
            select(Notification)
            .where(
                Notification.sent_at.is_(None),
                Notification.gave_up_at.is_(None),
                Notification.next_attempt_at <= now,
            )
            .order_by(Notification.next_attempt_at, Notification.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
