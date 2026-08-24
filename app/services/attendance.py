"""Finalized attendance and statistics.

    Signup status  →  Staff finalization  →  Attendance record  →  Statistics

Signup rows (operation_attendance) are never overwritten — the finalized
verdict lives in attendance_records, every change is audit-logged, and all
statistics are derived from the records so nothing can drift out of sync.

Attendance rate = attended / (attended + absent). Excused absences don't
count against anyone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.database import Database
from app.database.models.operation import (
    AttendanceStatus,
    Operation,
    OperationAttendance,
    OperationStatus,
)
from app.database.models.player import AttendanceRecord, FinalAttendance, Player
from app.database.repositories.operations import OperationRepository
from app.database.repositories.players import (
    AttendanceRecordRepository,
    PlayerRepository,
)
from app.errors import DatabaseError, ValidationError
from app.services.operations import OperationNotFoundError

log = logging.getLogger(__name__)

_FINALIZABLE = (OperationStatus.ACTIVE.value, OperationStatus.COMPLETED.value)


@dataclass(frozen=True)
class RosterEntry:
    discord_user_id: int
    display_name: str
    signup_status: str | None   # attending / maybe / declined / waitlist / None (walk-on)
    final_status: str | None    # attended / absent / excused / None (pending)


@dataclass(frozen=True)
class PlayerStats:
    signups: int
    attended: int
    absent: int
    excused: int

    @property
    def rate(self) -> float | None:
        judged = self.attended + self.absent
        return (self.attended / judged * 100) if judged else None


@dataclass(frozen=True)
class UnitStats:
    active_members: int
    operations_completed: int
    operations_this_month: int
    average_attended_per_operation: float | None
    overall_attendance_rate: float | None
    most_attended: tuple[str, int] | None  # (operation name, attended count)
    largest_signup: tuple[str, int] | None


class AttendanceService:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def _finalizable_operation(self, session, operation_id: int) -> Operation:
        operation = await OperationRepository(session).get(operation_id)
        if operation is None:
            raise OperationNotFoundError(operation_id)
        if operation.status not in _FINALIZABLE:
            raise ValidationError(
                f"operation is {operation.status}",
                user_message=(
                    "Attendance can only be finalized for active or completed "
                    "operations."
                ),
            )
        return operation

    async def finalization_roster(self, operation_id: int) -> list[RosterEntry]:
        """Signups merged with any existing finalized verdicts."""
        try:
            async with self._database.session() as session:
                signups = await OperationRepository(session).list_attendance(operation_id)
                finals = await AttendanceRecordRepository(session).list_for_operation(
                    operation_id
                )
        except SQLAlchemyError as exc:
            raise DatabaseError("finalization_roster failed") from exc
        final_by_user = {player.discord_user_id: record for record, player in finals}
        entries: list[RosterEntry] = []
        seen: set[int] = set()
        for signup in signups:
            record = final_by_user.get(signup.user_id)
            entries.append(
                RosterEntry(
                    discord_user_id=signup.user_id,
                    display_name=signup.display_name,
                    signup_status=signup.status,
                    final_status=record.status if record else None,
                )
            )
            seen.add(signup.user_id)
        for record, player in finals:  # finalized walk-ons without a signup
            if player.discord_user_id not in seen:
                entries.append(
                    RosterEntry(
                        discord_user_id=player.discord_user_id,
                        display_name=player.display_name,
                        signup_status=None,
                        final_status=record.status,
                    )
                )
        # attending first, then maybe/waitlist, then the rest, alphabetical
        order = {"attending": 0, "waitlist": 1, "maybe": 2, "declined": 4}
        entries.sort(key=lambda e: (order.get(e.signup_status or "", 3), e.display_name.lower()))
        return entries

    async def set_final_status(
        self,
        operation_id: int,
        guild_id: int,
        discord_user_id: int,
        display_name: str,
        status: FinalAttendance,
        changed_by: int,
    ) -> AttendanceRecord:
        """Finalize or correct one member's attendance (audit-logged)."""
        try:
            async with self._database.session() as session, session.begin():
                operation = await self._finalizable_operation(session, operation_id)
                if operation.guild_id != guild_id:
                    raise OperationNotFoundError(operation_id)
                player = await PlayerRepository(session).get_or_create(
                    guild_id, discord_user_id, display_name
                )
                return await AttendanceRecordRepository(session).set_status(
                    operation_id, player.id, status.value, changed_by
                )
        except SQLAlchemyError as exc:
            raise DatabaseError("set_final_status failed") from exc

    async def finalize_all_signed_up(
        self, operation_id: int, guild_id: int, changed_by: int
    ) -> int:
        """Mark every signed-up (attending/waitlist) member without a verdict
        as attended. Returns how many records were written."""
        try:
            async with self._database.session() as session, session.begin():
                operation = await self._finalizable_operation(session, operation_id)
                if operation.guild_id != guild_id:
                    raise OperationNotFoundError(operation_id)
                signups = await OperationRepository(session).list_attendance(operation_id)
                players = PlayerRepository(session)
                records = AttendanceRecordRepository(session)
                written = 0
                for signup in signups:
                    if signup.status not in (
                        AttendanceStatus.ATTENDING.value, AttendanceStatus.WAITLIST.value
                    ):
                        continue
                    player = await players.get_or_create(
                        guild_id, signup.user_id, signup.display_name
                    )
                    if await records.get(operation_id, player.id) is None:
                        await records.set_status(
                            operation_id, player.id, FinalAttendance.ATTENDED.value, changed_by
                        )
                        written += 1
                return written
        except SQLAlchemyError as exc:
            raise DatabaseError("finalize_all_signed_up failed") from exc

    async def corrections(self, operation_id: int, guild_id: int, discord_user_id: int):
        """Audit trail for one member's record on one operation."""
        try:
            async with self._database.session() as session:
                player = await PlayerRepository(session).get(guild_id, discord_user_id)
                if player is None:
                    return []
                repository = AttendanceRecordRepository(session)
                record = await repository.get(operation_id, player.id)
                if record is None:
                    return []
                return await repository.audits_for(record.id)
        except SQLAlchemyError as exc:
            raise DatabaseError("corrections failed") from exc

    # --- statistics -------------------------------------------------------------

    async def player_stats(self, guild_id: int, discord_user_id: int) -> PlayerStats:
        try:
            async with self._database.session() as session:
                repository = AttendanceRecordRepository(session)
                signups = await repository.signup_count_for_user(guild_id, discord_user_id)
                player = await PlayerRepository(session).get(guild_id, discord_user_id)
                counts = (
                    await repository.counts_for_player(player.id) if player is not None else {}
                )
        except SQLAlchemyError as exc:
            raise DatabaseError("player_stats failed") from exc
        return PlayerStats(
            signups=signups,
            attended=counts.get("attended", 0),
            absent=counts.get("absent", 0),
            excused=counts.get("excused", 0),
        )

    async def recent_history(
        self, guild_id: int, discord_user_id: int, limit: int = 5
    ) -> list[tuple[str, datetime, str]]:
        try:
            async with self._database.session() as session:
                player = await PlayerRepository(session).get(guild_id, discord_user_id)
                if player is None:
                    return []
                rows = await AttendanceRecordRepository(session).list_for_player(
                    player.id, limit
                )
        except SQLAlchemyError as exc:
            raise DatabaseError("recent_history failed") from exc
        return [(op.name, op.scheduled_at, record.status) for record, op in rows]

    async def attendance_leaders(
        self, guild_id: int, since: datetime, limit: int = 5
    ) -> list[tuple[str, int]]:
        """Staff-only aggregate: top attended counts since a date."""
        try:
            async with self._database.session() as session:
                rows = await AttendanceRecordRepository(session).attended_counts_since(
                    guild_id, since
                )
        except SQLAlchemyError as exc:
            raise DatabaseError("attendance_leaders failed") from exc
        return [(player.display_name, count) for player, count in rows[:limit]]

    async def unit_stats(self, guild_id: int) -> UnitStats:
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        try:
            async with self._database.session() as session:
                active_members = await PlayerRepository(session).count_active(guild_id)

                completed = await session.execute(
                    select(func.count()).select_from(Operation).where(
                        Operation.guild_id == guild_id,
                        Operation.status == OperationStatus.COMPLETED.value,
                    )
                )
                operations_completed = int(completed.scalar_one())

                this_month = await session.execute(
                    select(func.count()).select_from(Operation).where(
                        Operation.guild_id == guild_id,
                        Operation.scheduled_at >= month_start,
                        Operation.status != OperationStatus.CANCELLED.value,
                    )
                )
                operations_this_month = int(this_month.scalar_one())

                per_status = await session.execute(
                    select(AttendanceRecord.status, func.count())
                    .join(Operation, AttendanceRecord.operation_id == Operation.id)
                    .where(Operation.guild_id == guild_id)
                    .group_by(AttendanceRecord.status)
                )
                counts = {row[0]: row[1] for row in per_status.all()}

                attended_per_op = await session.execute(
                    select(Operation.name, func.count())
                    .join(AttendanceRecord, AttendanceRecord.operation_id == Operation.id)
                    .where(
                        Operation.guild_id == guild_id,
                        AttendanceRecord.status == "attended",
                    )
                    .group_by(Operation.id)
                    .order_by(func.count().desc())
                )
                attended_rows = attended_per_op.all()

                signups_per_op = await session.execute(
                    select(Operation.name, func.count())
                    .join(OperationAttendance, OperationAttendance.operation_id == Operation.id)
                    .where(
                        Operation.guild_id == guild_id,
                        OperationAttendance.status.in_(("attending", "waitlist")),
                    )
                    .group_by(Operation.id)
                    .order_by(func.count().desc())
                )
                signup_rows = signups_per_op.all()
        except SQLAlchemyError as exc:
            raise DatabaseError("unit_stats failed") from exc

        attended = counts.get("attended", 0)
        judged = attended + counts.get("absent", 0)
        return UnitStats(
            active_members=active_members,
            operations_completed=operations_completed,
            operations_this_month=operations_this_month,
            average_attended_per_operation=(
                sum(count for _, count in attended_rows) / len(attended_rows)
                if attended_rows else None
            ),
            overall_attendance_rate=(attended / judged * 100) if judged else None,
            most_attended=(attended_rows[0][0], attended_rows[0][1]) if attended_rows else None,
            largest_signup=(signup_rows[0][0], signup_rows[0][1]) if signup_rows else None,
        )
