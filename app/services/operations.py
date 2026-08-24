"""Operation business logic: scheduling, lifecycle, attendance, reminders.

A Mission is reusable content (GitHub); an Operation is a scheduled instance
of one. All rules live here — Discord cogs only render results. The reminder
system is deliberately database-driven (sent-at timestamps, not in-memory
timers) so it survives restarts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.exc import SQLAlchemyError

from app.database import Database
from app.database.models.guild import GuildConfiguration
from app.database.models.operation import (
    ALLOWED_TRANSITIONS,
    AttendanceStatus,
    Operation,
    OperationAttendance,
    OperationStatus,
)
from app.database.repositories.guilds import GuildConfigurationRepository
from app.database.repositories.operations import OperationRepository
from app.errors import AppError, DatabaseError, NotFoundError, ValidationError
from app.services.guilds import validate_timezone

log = logging.getLogger(__name__)

REMINDER_24H = timedelta(hours=24)
REMINDER_1H = timedelta(hours=1)


class OperationNotFoundError(NotFoundError):
    def __init__(self, operation_id: int) -> None:
        super().__init__(
            f"operation {operation_id} not found",
            user_message="That operation could not be found — it may have been removed.",
        )


class SignupsClosedError(AppError):
    default_user_message = "Signups for this operation are closed."


@dataclass(frozen=True)
class AttendanceOutcome:
    operation: Operation
    status: str  # the status actually stored (may be 'waitlist' when full)
    waitlist_position: int | None
    promoted: tuple[OperationAttendance, ...]  # members moved off the waitlist


@dataclass(frozen=True)
class Roster:
    attending: list[OperationAttendance]
    maybe: list[OperationAttendance]
    declined: list[OperationAttendance]
    waitlist: list[OperationAttendance]


@dataclass(frozen=True)
class DueReminder:
    operation: Operation
    kind: str  # "24h" | "1h"
    attendee_ids: tuple[int, ...]


@dataclass(frozen=True)
class TickResult:
    reminders: tuple[DueReminder, ...] = ()
    activated: tuple[Operation, ...] = ()   # flipped to ACTIVE at start time
    to_archive: tuple[Operation, ...] = ()  # posts due to move to the logs channel


@dataclass(frozen=True)
class ProfileSummary:
    upcoming: list[tuple[OperationAttendance, Operation]]
    attended_count: int
    responded_count: int


def _utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


class OperationService:
    def __init__(self, database: Database) -> None:
        self._database = database

    # --- scheduling -----------------------------------------------------------

    def parse_local_datetime(self, date_text: str, time_text: str, tz_name: str) -> datetime:
        """Parse staff-typed date + time in the guild timezone; returns UTC."""
        tz = ZoneInfo(validate_timezone(tz_name))
        date_text, time_text = date_text.strip(), time_text.strip()
        parsed_date = None
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
            try:
                parsed_date = datetime.strptime(date_text, fmt).date()
                break
            except ValueError:
                continue
        if parsed_date is None:
            raise ValidationError(
                f"unparseable date {date_text!r}",
                user_message=f"Could not read the date `{date_text}` — use `DD/MM/YYYY` (e.g. `05/09/2026`).",
            )
        try:
            parsed_time = datetime.strptime(time_text, "%H:%M").time()
        except ValueError as exc:
            raise ValidationError(
                f"unparseable time {time_text!r}",
                user_message=f"Could not read the time `{time_text}` — use 24h `HH:MM` (e.g. `20:00`).",
            ) from exc
        local = datetime.combine(parsed_date, parsed_time, tzinfo=tz)
        return local.astimezone(timezone.utc)

    async def create_operation(
        self,
        *,
        guild_id: int,
        mission_id: str,
        mission_name: str,
        mission_status: str,
        scheduled_at_utc: datetime,
        tz_name: str,
        created_by: int,
        name: str | None = None,
        server_name: str | None = None,
        max_players: int | None = None,
        allow_archived: bool = False,
    ) -> Operation:
        if mission_status == "archived" and not allow_archived:
            raise ValidationError(
                "mission archived",
                user_message=(
                    f"Mission `{mission_id}` is archived. Staff must restore it (or "
                    "explicitly schedule it anyway) before it can be used."
                ),
            )
        if _utc(scheduled_at_utc) <= datetime.now(timezone.utc):
            raise ValidationError(
                "scheduled in the past",
                user_message="The operation time is in the past — pick a future date/time.",
            )
        if max_players is not None and (max_players < 1 or max_players > 300):
            raise ValidationError(
                "bad capacity", user_message="Max players must be between 1 and 300."
            )
        try:
            async with self._database.session() as session, session.begin():
                operation = await OperationRepository(session).create(
                    {
                        "guild_id": guild_id,
                        "mission_id": mission_id.upper(),
                        "name": (name or mission_name)[:100],
                        "scheduled_at": _utc(scheduled_at_utc),
                        "timezone": validate_timezone(tz_name),
                        "server_name": server_name[:100] if server_name else None,
                        "max_players": max_players,
                        "status": OperationStatus.SCHEDULED.value,
                        "created_by": created_by,
                    }
                )
            log.info(
                "Created operation %d (%s) for guild %s at %s",
                operation.id, operation.name, guild_id, operation.scheduled_at,
            )
            return operation
        except SQLAlchemyError as exc:
            log.exception("Failed to create operation")
            raise DatabaseError("create_operation failed") from exc

    async def get(self, operation_id: int) -> Operation:
        try:
            async with self._database.session() as session:
                operation = await OperationRepository(session).get(operation_id)
        except SQLAlchemyError as exc:
            raise DatabaseError(f"get({operation_id}) failed") from exc
        if operation is None:
            raise OperationNotFoundError(operation_id)
        return operation

    async def list_upcoming(self, guild_id: int) -> list[Operation]:
        try:
            async with self._database.session() as session:
                return await OperationRepository(session).list_upcoming(guild_id)
        except SQLAlchemyError as exc:
            raise DatabaseError("list_upcoming failed") from exc

    async def discard_unpublished(self, operation_id: int) -> None:
        """Delete an operation that was never posted (create-flow cancel)."""
        try:
            async with self._database.session() as session, session.begin():
                repository = OperationRepository(session)
                operation = await repository.get(operation_id)
                if operation is None:
                    return
                if operation.message_id is not None:
                    raise ValidationError(
                        "operation already published",
                        user_message="This operation is already posted — cancel it instead.",
                    )
                await repository.delete(operation)
        except SQLAlchemyError as exc:
            raise DatabaseError("discard_unpublished failed") from exc

    async def mark_published(
        self, operation_id: int, channel_id: int, message_id: int
    ) -> Operation:
        return await self._update(
            operation_id,
            status_to=OperationStatus.OPEN,
            channel_id=channel_id,
            message_id=message_id,
        )

    async def set_message(self, operation_id: int, channel_id: int, message_id: int) -> Operation:
        """Repoint an operation at a new Discord post (repost after deletion)."""
        return await self._update(operation_id, channel_id=channel_id, message_id=message_id)

    async def set_objectives_snapshot(self, operation_id: int, text: str) -> Operation:
        return await self._update(operation_id, objectives_snapshot=text)

    async def transition(self, operation_id: int, new_status: OperationStatus) -> Operation:
        fields: dict[str, object] = {}
        if new_status is OperationStatus.CANCELLED:
            # Starts the 24h clock before the post is moved to the logs channel.
            fields["cancelled_at"] = datetime.now(timezone.utc)
        return await self._update(operation_id, status_to=new_status, **fields)

    async def set_brief_messages(
        self, operation_id: int, channel_id: int, message_ids: list[int]
    ) -> Operation:
        return await self._update(
            operation_id, brief_channel_id=channel_id, brief_message_ids=message_ids
        )

    async def mark_archived(self, operation_id: int) -> Operation:
        return await self._update(operation_id, archived_at=datetime.now(timezone.utc))

    async def reschedule(
        self, operation_id: int, scheduled_at_utc: datetime
    ) -> Operation:
        if _utc(scheduled_at_utc) <= datetime.now(timezone.utc):
            raise ValidationError(
                "scheduled in the past",
                user_message="The new time is in the past — pick a future date/time.",
            )
        return await self._update(
            operation_id,
            scheduled_at=_utc(scheduled_at_utc),
            # a moved operation gets fresh reminders
            reminder_24h_sent_at=None,
            reminder_1h_sent_at=None,
        )

    async def _update(
        self,
        operation_id: int,
        *,
        status_to: OperationStatus | None = None,
        **fields: object,
    ) -> Operation:
        try:
            async with self._database.session() as session, session.begin():
                repository = OperationRepository(session)
                operation = await repository.get(operation_id)
                if operation is None:
                    raise OperationNotFoundError(operation_id)
                if status_to is not None:
                    current = OperationStatus(operation.status)
                    if status_to is not current:
                        if status_to not in ALLOWED_TRANSITIONS[current]:
                            raise ValidationError(
                                f"invalid transition {current.value} -> {status_to.value}",
                                user_message=(
                                    f"An operation can't go from **{current.value}** "
                                    f"to **{status_to.value}**."
                                ),
                            )
                        operation.status = status_to.value
                for key, value in fields.items():
                    setattr(operation, key, value)
                await session.flush()
                await session.refresh(operation)
                return operation
        except SQLAlchemyError as exc:
            log.exception("Failed to update operation %d", operation_id)
            raise DatabaseError(f"update operation {operation_id} failed") from exc

    # --- attendance -----------------------------------------------------------

    async def set_attendance(
        self, operation_id: int, user_id: int, display_name: str, requested: AttendanceStatus
    ) -> AttendanceOutcome:
        if requested is AttendanceStatus.WAITLIST:
            raise ValueError("waitlist is assigned by capacity rules, not requested")
        try:
            async with self._database.session() as session, session.begin():
                repository = OperationRepository(session)
                operation = await repository.get(operation_id)
                if operation is None:
                    raise OperationNotFoundError(operation_id)
                if operation.status != OperationStatus.OPEN.value:
                    raise SignupsClosedError(f"operation {operation_id} is {operation.status}")

                now = datetime.now(timezone.utc)
                record = await repository.get_response(operation_id, user_id)
                if record is None:
                    record = OperationAttendance(
                        operation_id=operation_id,
                        user_id=user_id,
                        display_name=display_name[:100],
                        status=AttendanceStatus.DECLINED.value,
                    )
                    session.add(record)
                record.display_name = display_name[:100]

                stored = requested
                position: int | None = None
                if requested is AttendanceStatus.ATTENDING and operation.max_players is not None:
                    counts = await repository.count_by_status(operation_id)
                    attending = counts[AttendanceStatus.ATTENDING.value]
                    already_attending = record.status == AttendanceStatus.ATTENDING.value
                    if not already_attending and attending >= operation.max_players:
                        stored = AttendanceStatus.WAITLIST
                        if record.status != AttendanceStatus.WAITLIST.value:
                            record.waitlisted_at = now
                if stored is not AttendanceStatus.WAITLIST:
                    record.waitlisted_at = None
                record.status = stored.value
                await session.flush()

                promoted = await self._reconcile_waitlist(repository, operation)
                if stored is AttendanceStatus.WAITLIST:
                    # position after reconciliation (we may have just been promoted)
                    await session.refresh(record)
                    if record.status == AttendanceStatus.WAITLIST.value:
                        waitlist = await repository.waitlist_in_order(operation_id)
                        position = next(
                            (i + 1 for i, r in enumerate(waitlist) if r.user_id == user_id),
                            None,
                        )
                    else:
                        stored = AttendanceStatus(record.status)
                return AttendanceOutcome(
                    operation=operation,
                    status=stored.value,
                    waitlist_position=position,
                    promoted=tuple(p for p in promoted if p.user_id != user_id),
                )
        except SQLAlchemyError as exc:
            log.exception("Failed to set attendance")
            raise DatabaseError("set_attendance failed") from exc

    async def _reconcile_waitlist(
        self, repository: OperationRepository, operation: Operation
    ) -> list[OperationAttendance]:
        """Fill free confirmed slots from the waitlist, oldest first.

        With no capacity set, every waitlisted member is promoted (this only
        happens when a capacity is removed after people already queued).
        """
        capacity = operation.max_players if operation.max_players is not None else float("inf")
        counts = await repository.count_by_status(operation.id)
        attending = counts[AttendanceStatus.ATTENDING.value]
        promoted: list[OperationAttendance] = []
        for record in await repository.waitlist_in_order(operation.id):
            if attending >= capacity:
                break
            record.status = AttendanceStatus.ATTENDING.value
            record.waitlisted_at = None
            attending += 1
            promoted.append(record)
        return promoted

    async def roster(self, operation_id: int) -> Roster:
        try:
            async with self._database.session() as session:
                records = await OperationRepository(session).list_attendance(operation_id)
        except SQLAlchemyError as exc:
            raise DatabaseError("roster failed") from exc
        waitlist = sorted(
            (r for r in records if r.status == AttendanceStatus.WAITLIST.value),
            key=lambda r: (r.waitlisted_at or r.responded_at),
        )
        return Roster(
            attending=[r for r in records if r.status == AttendanceStatus.ATTENDING.value],
            maybe=[r for r in records if r.status == AttendanceStatus.MAYBE.value],
            declined=[r for r in records if r.status == AttendanceStatus.DECLINED.value],
            waitlist=waitlist,
        )

    async def attendance_counts(self, operation_id: int) -> dict[str, int]:
        try:
            async with self._database.session() as session:
                return await OperationRepository(session).count_by_status(operation_id)
        except SQLAlchemyError as exc:
            raise DatabaseError("attendance_counts failed") from exc

    async def user_profile(self, guild_id: int, user_id: int) -> ProfileSummary:
        try:
            async with self._database.session() as session:
                rows = await OperationRepository(session).list_user_attendance(guild_id, user_id)
        except SQLAlchemyError as exc:
            raise DatabaseError("user_profile failed") from exc
        now = datetime.now(timezone.utc)
        upcoming = [
            (attendance, operation)
            for attendance, operation in rows
            if _utc(operation.scheduled_at) > now
            and operation.status
            in (OperationStatus.OPEN.value, OperationStatus.LOCKED.value,
                OperationStatus.SCHEDULED.value)
            and attendance.status
            in (AttendanceStatus.ATTENDING.value, AttendanceStatus.MAYBE.value,
                AttendanceStatus.WAITLIST.value)
        ]
        attended = sum(
            1
            for attendance, operation in rows
            if operation.status == OperationStatus.COMPLETED.value
            and attendance.status == AttendanceStatus.ATTENDING.value
        )
        return ProfileSummary(
            upcoming=upcoming, attended_count=attended, responded_count=len(rows)
        )

    # --- reminders & automatic transitions -------------------------------------

    async def tick(self, now: datetime | None = None) -> TickResult:
        """One scheduler pass: collect due reminders, apply auto-transitions.

        Reminder state is persisted per operation, so a restarted bot resumes
        exactly where it left off. A reminder window that was missed entirely
        (bot down past the start time) is skipped rather than sent late.
        """
        now = _utc(now or datetime.now(timezone.utc))
        reminders: list[DueReminder] = []
        activated: list[Operation] = []
        to_archive: list[Operation] = []
        try:
            async with self._database.session() as session, session.begin():
                repository = OperationRepository(session)
                configurations: dict[int, GuildConfiguration | None] = {}
                guild_repo = GuildConfigurationRepository(session)

                for operation in await repository.list_unarchived_terminal():
                    if operation.status == OperationStatus.COMPLETED.value:
                        to_archive.append(operation)
                    elif operation.cancelled_at is not None and _utc(
                        operation.cancelled_at
                    ) <= now - timedelta(hours=24):
                        to_archive.append(operation)

                for operation in await repository.list_needing_tick(now):
                    scheduled = _utc(operation.scheduled_at)
                    if scheduled <= now:
                        if operation.status in (
                            OperationStatus.OPEN.value,
                            OperationStatus.LOCKED.value,
                        ):
                            operation.status = OperationStatus.ACTIVE.value
                            activated.append(operation)
                        continue

                    if operation.guild_id not in configurations:
                        configurations[operation.guild_id] = await guild_repo.get_by_guild_id(
                            operation.guild_id
                        )
                    configuration = configurations[operation.guild_id]
                    if configuration is not None and not configuration.reminders_enabled:
                        continue
                    if operation.message_id is None:
                        continue  # never posted; nothing to remind against

                    created = _utc(operation.created_at)
                    for kind, window, sent_field in (
                        ("24h", REMINDER_24H, "reminder_24h_sent_at"),
                        ("1h", REMINDER_1H, "reminder_1h_sent_at"),
                    ):
                        if getattr(operation, sent_field) is not None:
                            continue
                        if scheduled - now > window:
                            continue
                        # Don't fire a "24h before" ping for an op created 2h before start.
                        if created > scheduled - window:
                            setattr(operation, sent_field, now)
                            continue
                        setattr(operation, sent_field, now)
                        attendees = [
                            r.user_id
                            for r in await repository.list_attendance(operation.id)
                            if r.status == AttendanceStatus.ATTENDING.value
                        ]
                        reminders.append(
                            DueReminder(
                                operation=operation, kind=kind, attendee_ids=tuple(attendees)
                            )
                        )
        except SQLAlchemyError as exc:
            log.exception("Scheduler tick failed")
            raise DatabaseError("tick failed") from exc
        return TickResult(
            reminders=tuple(reminders),
            activated=tuple(activated),
            to_archive=tuple(to_archive),
        )
