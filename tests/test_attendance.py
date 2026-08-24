from datetime import datetime, timedelta, timezone

import pytest

from app.database.models.operation import AttendanceStatus, OperationStatus
from app.services.operations import OperationService, SignupsClosedError


async def open_operation(database, capacity: int | None = 2):
    service = OperationService(database)
    operation = await service.create_operation(
        guild_id=1,
        mission_id="OP-001",
        mission_name="Blackout",
        mission_status="ready",
        scheduled_at_utc=datetime.now(timezone.utc) + timedelta(days=2),
        tz_name="UTC",
        created_by=100,
        max_players=capacity,
    )
    operation = await service.mark_published(operation.id, channel_id=5, message_id=6)
    return service, operation


async def test_no_member_limit_by_default(database):
    """The unit runs without a capacity — everyone who clicks Attend gets in."""
    service, operation = await open_operation(database, capacity=None)
    for user_id in range(1, 60):
        outcome = await service.set_attendance(
            operation.id, user_id, f"User{user_id}", AttendanceStatus.ATTENDING
        )
        assert outcome.status == "attending"
    roster = await service.roster(operation.id)
    assert len(roster.attending) == 59
    assert roster.waitlist == []


async def test_attend_maybe_decline_and_change(database):
    service, operation = await open_operation(database, capacity=10)

    outcome = await service.set_attendance(operation.id, 1, "Alpha", AttendanceStatus.ATTENDING)
    assert outcome.status == "attending"
    outcome = await service.set_attendance(operation.id, 2, "Bravo", AttendanceStatus.MAYBE)
    assert outcome.status == "maybe"
    outcome = await service.set_attendance(operation.id, 3, "Charlie", AttendanceStatus.DECLINED)
    assert outcome.status == "declined"

    # changing a response updates it in place — no duplicates
    outcome = await service.set_attendance(operation.id, 1, "Alpha", AttendanceStatus.DECLINED)
    assert outcome.status == "declined"
    roster = await service.roster(operation.id)
    assert len(roster.attending) == 0
    assert [record.user_id for record in roster.declined] == [1, 3]
    counts = await service.attendance_counts(operation.id)
    assert counts["maybe"] == 1 and counts["declined"] == 2


async def test_capacity_overflow_goes_to_waitlist(database):
    service, operation = await open_operation(database, capacity=2)
    await service.set_attendance(operation.id, 1, "Alpha", AttendanceStatus.ATTENDING)
    await service.set_attendance(operation.id, 2, "Bravo", AttendanceStatus.ATTENDING)

    outcome = await service.set_attendance(operation.id, 3, "Charlie", AttendanceStatus.ATTENDING)
    assert outcome.status == "waitlist"
    assert outcome.waitlist_position == 1
    outcome = await service.set_attendance(operation.id, 4, "Delta", AttendanceStatus.ATTENDING)
    assert outcome.waitlist_position == 2


async def test_waitlist_promotion_when_slot_opens(database):
    service, operation = await open_operation(database, capacity=2)
    await service.set_attendance(operation.id, 1, "Alpha", AttendanceStatus.ATTENDING)
    await service.set_attendance(operation.id, 2, "Bravo", AttendanceStatus.ATTENDING)
    await service.set_attendance(operation.id, 3, "Charlie", AttendanceStatus.ATTENDING)  # waitlist

    # Bravo drops out -> Charlie is promoted automatically
    outcome = await service.set_attendance(operation.id, 2, "Bravo", AttendanceStatus.DECLINED)
    assert [record.user_id for record in outcome.promoted] == [3]
    roster = await service.roster(operation.id)
    assert sorted(record.user_id for record in roster.attending) == [1, 3]
    assert roster.waitlist == []


async def test_waitlist_promotion_is_fifo(database):
    service, operation = await open_operation(database, capacity=1)
    await service.set_attendance(operation.id, 1, "Alpha", AttendanceStatus.ATTENDING)
    await service.set_attendance(operation.id, 2, "Bravo", AttendanceStatus.ATTENDING)
    await service.set_attendance(operation.id, 3, "Charlie", AttendanceStatus.ATTENDING)

    outcome = await service.set_attendance(operation.id, 1, "Alpha", AttendanceStatus.DECLINED)
    assert [record.user_id for record in outcome.promoted] == [2]  # first in, first promoted
    roster = await service.roster(operation.id)
    assert [record.user_id for record in roster.waitlist] == [3]


async def test_attending_member_switching_to_attending_is_stable(database):
    service, operation = await open_operation(database, capacity=1)
    await service.set_attendance(operation.id, 1, "Alpha", AttendanceStatus.ATTENDING)
    outcome = await service.set_attendance(operation.id, 1, "Alpha", AttendanceStatus.ATTENDING)
    assert outcome.status == "attending"  # not bumped to its own waitlist


async def test_signups_closed_when_locked_or_cancelled(database):
    service, operation = await open_operation(database)
    await service.transition(operation.id, OperationStatus.LOCKED)
    with pytest.raises(SignupsClosedError):
        await service.set_attendance(operation.id, 1, "Alpha", AttendanceStatus.ATTENDING)
    await service.transition(operation.id, OperationStatus.CANCELLED)
    with pytest.raises(SignupsClosedError):
        await service.set_attendance(operation.id, 1, "Alpha", AttendanceStatus.MAYBE)


async def test_profile_summary(database):
    service, operation = await open_operation(database, capacity=10)
    await service.set_attendance(operation.id, 1, "Alpha", AttendanceStatus.ATTENDING)

    # a completed op in the past counts as attended
    _, done = await open_operation(database, capacity=10)
    await service.set_attendance(done.id, 1, "Alpha", AttendanceStatus.ATTENDING)
    await service.transition(done.id, OperationStatus.ACTIVE)
    await service.transition(done.id, OperationStatus.COMPLETED)

    summary = await service.user_profile(1, 1)
    assert [op.id for _, op in summary.upcoming] == [operation.id]
    assert summary.attended_count == 1
    assert summary.responded_count == 2
