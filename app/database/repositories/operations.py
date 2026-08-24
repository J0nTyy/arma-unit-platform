"""Data access for operations, attendance and mission publications."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.operation import (
    AttendanceStatus,
    MissionPublication,
    Operation,
    OperationAttendance,
    OperationStatus,
)

_UPCOMING_STATUSES = (
    OperationStatus.SCHEDULED.value,
    OperationStatus.OPEN.value,
    OperationStatus.LOCKED.value,
    OperationStatus.ACTIVE.value,
)


class OperationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, operation_id: int) -> Operation | None:
        return await self._session.get(Operation, operation_id)

    async def create(self, values: dict[str, Any]) -> Operation:
        operation = Operation(**values)
        self._session.add(operation)
        await self._session.flush()
        await self._session.refresh(operation)
        return operation

    async def delete(self, operation: Operation) -> None:
        await self._session.delete(operation)
        await self._session.flush()

    async def list_upcoming(self, guild_id: int, limit: int = 25) -> list[Operation]:
        result = await self._session.execute(
            select(Operation)
            .where(Operation.guild_id == guild_id, Operation.status.in_(_UPCOMING_STATUSES))
            .order_by(Operation.scheduled_at)
            .limit(limit)
        )
        return list(result.scalars())

    async def list_needing_tick(self, now: datetime) -> list[Operation]:
        """Operations that may need reminders or automatic transitions."""
        result = await self._session.execute(
            select(Operation).where(
                Operation.status.in_(
                    (
                        OperationStatus.OPEN.value,
                        OperationStatus.LOCKED.value,
                        OperationStatus.ACTIVE.value,
                    )
                )
            )
        )
        return list(result.scalars())

    async def list_recent_finalizable(self, guild_id: int, limit: int = 15) -> list[Operation]:
        """Recent operations whose attendance staff may finalize."""
        result = await self._session.execute(
            select(Operation)
            .where(
                Operation.guild_id == guild_id,
                Operation.status.in_(
                    (OperationStatus.ACTIVE.value, OperationStatus.COMPLETED.value)
                ),
            )
            .order_by(Operation.scheduled_at.desc())
            .limit(limit)
        )
        return list(result.scalars())

    async def list_unarchived_terminal(self) -> list[Operation]:
        """Completed/cancelled operations whose posts still sit in the
        attendance channel and are waiting to be moved to the logs."""
        result = await self._session.execute(
            select(Operation).where(
                Operation.status.in_(
                    (OperationStatus.COMPLETED.value, OperationStatus.CANCELLED.value)
                ),
                Operation.archived_at.is_(None),
                Operation.message_id.is_not(None),
            )
        )
        return list(result.scalars())

    # --- attendance ----------------------------------------------------------

    async def get_response(self, operation_id: int, user_id: int) -> OperationAttendance | None:
        result = await self._session.execute(
            select(OperationAttendance).where(
                OperationAttendance.operation_id == operation_id,
                OperationAttendance.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_attendance(self, operation_id: int) -> list[OperationAttendance]:
        result = await self._session.execute(
            select(OperationAttendance)
            .where(OperationAttendance.operation_id == operation_id)
            .order_by(OperationAttendance.responded_at)
        )
        return list(result.scalars())

    async def count_by_status(self, operation_id: int) -> dict[str, int]:
        result = await self._session.execute(
            select(OperationAttendance.status, func.count())
            .where(OperationAttendance.operation_id == operation_id)
            .group_by(OperationAttendance.status)
        )
        counts = {status.value: 0 for status in AttendanceStatus}
        counts.update({row[0]: row[1] for row in result.all()})
        return counts

    async def waitlist_in_order(self, operation_id: int) -> list[OperationAttendance]:
        result = await self._session.execute(
            select(OperationAttendance)
            .where(
                OperationAttendance.operation_id == operation_id,
                OperationAttendance.status == AttendanceStatus.WAITLIST.value,
            )
            .order_by(OperationAttendance.waitlisted_at)
        )
        return list(result.scalars())

    async def list_user_attendance(
        self, guild_id: int, user_id: int
    ) -> list[tuple[OperationAttendance, Operation]]:
        result = await self._session.execute(
            select(OperationAttendance, Operation)
            .join(Operation, OperationAttendance.operation_id == Operation.id)
            .where(Operation.guild_id == guild_id, OperationAttendance.user_id == user_id)
            .order_by(Operation.scheduled_at)
        )
        return [(row[0], row[1]) for row in result.all()]


class MissionPublicationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, guild_id: int, mission_id: str) -> MissionPublication | None:
        result = await self._session.execute(
            select(MissionPublication).where(
                MissionPublication.guild_id == guild_id,
                func.upper(MissionPublication.mission_id) == mission_id.strip().upper(),
            )
        )
        return result.scalars().first()

    async def list_for_guild(self, guild_id: int) -> list[MissionPublication]:
        result = await self._session.execute(
            select(MissionPublication).where(MissionPublication.guild_id == guild_id)
        )
        return list(result.scalars())

    async def record(self, values: dict[str, Any]) -> MissionPublication:
        publication = MissionPublication(**values)
        self._session.add(publication)
        await self._session.flush()
        await self._session.refresh(publication)
        return publication

    async def remove(self, publication_id: int) -> None:
        await self._session.execute(
            delete(MissionPublication).where(MissionPublication.id == publication_id)
        )
