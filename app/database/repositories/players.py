"""Data access for players, qualifications and finalized attendance."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.operation import Operation, OperationAttendance
from app.database.models.player import (
    AttendanceAudit,
    AttendanceRecord,
    Player,
    PlayerQualification,
)


class PlayerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, guild_id: int, discord_user_id: int) -> Player | None:
        result = await self._session.execute(
            select(Player).where(
                Player.guild_id == guild_id, Player.discord_user_id == discord_user_id
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, player_id: int) -> Player | None:
        return await self._session.get(Player, player_id)

    async def get_or_create(
        self,
        guild_id: int,
        discord_user_id: int,
        display_name: str,
        joined_at: datetime | None = None,
    ) -> Player:
        player = await self.get(guild_id, discord_user_id)
        if player is None:
            player = Player(
                guild_id=guild_id,
                discord_user_id=discord_user_id,
                display_name=display_name[:100],
            )
            if joined_at is not None:
                player.join_date = joined_at
            self._session.add(player)
        else:
            player.display_name = display_name[:100]
            player.left_at = None  # they're demonstrably here (rejoin-safe)
        await self._session.flush()
        await self._session.refresh(player)
        return player

    async def search(
        self, guild_id: int, query: str | None = None, limit: int = 20
    ) -> list[Player]:
        statement = (
            select(Player).where(Player.guild_id == guild_id).order_by(Player.display_name)
        )
        if query:
            statement = statement.where(Player.display_name.ilike(f"%{query.strip()}%"))
        result = await self._session.execute(statement.limit(limit))
        return list(result.scalars())

    async def count_active(self, guild_id: int) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(Player)
            .where(
                Player.guild_id == guild_id,
                Player.active_status == "active",
                Player.left_at.is_(None),
            )
        )
        return int(result.scalar_one())


class QualificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for(self, player_id: int) -> list[PlayerQualification]:
        result = await self._session.execute(
            select(PlayerQualification)
            .where(PlayerQualification.player_id == player_id)
            .order_by(PlayerQualification.granted_at)
        )
        return list(result.scalars())

    async def get(self, player_id: int, qualification: str) -> PlayerQualification | None:
        result = await self._session.execute(
            select(PlayerQualification).where(
                PlayerQualification.player_id == player_id,
                PlayerQualification.qualification == qualification,
            )
        )
        return result.scalar_one_or_none()

    async def grant(self, player_id: int, qualification: str, granted_by: int) -> PlayerQualification:
        row = PlayerQualification(
            player_id=player_id, qualification=qualification, granted_by=granted_by
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def revoke(self, row: PlayerQualification) -> None:
        await self._session.delete(row)
        await self._session.flush()


class AttendanceRecordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, operation_id: int, player_id: int) -> AttendanceRecord | None:
        result = await self._session.execute(
            select(AttendanceRecord).where(
                AttendanceRecord.operation_id == operation_id,
                AttendanceRecord.player_id == player_id,
            )
        )
        return result.scalar_one_or_none()

    async def set_status(
        self, operation_id: int, player_id: int, status: str, changed_by: int
    ) -> AttendanceRecord:
        """Create or update a record, always writing an audit row."""
        record = await self.get(operation_id, player_id)
        previous: str | None = None
        if record is None:
            record = AttendanceRecord(
                operation_id=operation_id, player_id=player_id,
                status=status, finalized_by=changed_by,
            )
            self._session.add(record)
        else:
            previous = record.status
            record.status = status
            record.finalized_by = changed_by
        await self._session.flush()
        if previous != status:
            self._session.add(
                AttendanceAudit(
                    record_id=record.id, previous_status=previous,
                    new_status=status, changed_by=changed_by,
                )
            )
            await self._session.flush()
        return record

    async def list_for_operation(self, operation_id: int) -> list[tuple[AttendanceRecord, Player]]:
        result = await self._session.execute(
            select(AttendanceRecord, Player)
            .join(Player, AttendanceRecord.player_id == Player.id)
            .where(AttendanceRecord.operation_id == operation_id)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def list_for_player(
        self, player_id: int, limit: int = 10
    ) -> list[tuple[AttendanceRecord, Operation]]:
        result = await self._session.execute(
            select(AttendanceRecord, Operation)
            .join(Operation, AttendanceRecord.operation_id == Operation.id)
            .where(AttendanceRecord.player_id == player_id)
            .order_by(Operation.scheduled_at.desc())
            .limit(limit)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def counts_for_player(self, player_id: int) -> dict[str, int]:
        result = await self._session.execute(
            select(AttendanceRecord.status, func.count())
            .where(AttendanceRecord.player_id == player_id)
            .group_by(AttendanceRecord.status)
        )
        return {row[0]: row[1] for row in result.all()}

    async def audits_for(self, record_id: int) -> list[AttendanceAudit]:
        result = await self._session.execute(
            select(AttendanceAudit)
            .where(AttendanceAudit.record_id == record_id)
            .order_by(AttendanceAudit.changed_at)
        )
        return list(result.scalars())

    async def signup_count_for_user(self, guild_id: int, discord_user_id: int) -> int:
        """Signups (attending/waitlist) across this guild's operations."""
        result = await self._session.execute(
            select(func.count())
            .select_from(OperationAttendance)
            .join(Operation, OperationAttendance.operation_id == Operation.id)
            .where(
                Operation.guild_id == guild_id,
                OperationAttendance.user_id == discord_user_id,
                OperationAttendance.status.in_(("attending", "waitlist")),
            )
        )
        return int(result.scalar_one())

    async def attended_counts_since(
        self, guild_id: int, since: datetime
    ) -> list[tuple[Player, int]]:
        """Per-player attended counts for operations scheduled after `since`."""
        result = await self._session.execute(
            select(Player, func.count())
            .join(AttendanceRecord, AttendanceRecord.player_id == Player.id)
            .join(Operation, AttendanceRecord.operation_id == Operation.id)
            .where(
                Operation.guild_id == guild_id,
                AttendanceRecord.status == "attended",
                Operation.scheduled_at >= since,
            )
            .group_by(Player.id)
            .order_by(func.count().desc())
        )
        return [(row[0], row[1]) for row in result.all()]
