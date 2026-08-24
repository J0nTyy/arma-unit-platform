"""Attendance finalization, corrections with audit, statistics."""

from datetime import datetime, timedelta, timezone

import pytest

from app.database.models.operation import AttendanceStatus, OperationStatus
from app.database.models.player import FinalAttendance
from app.errors import ValidationError
from app.services import AttendanceService, OperationService, PlayerService


async def completed_operation(database, *, signups=()):
    operations = OperationService(database)
    operation = await operations.create_operation(
        guild_id=1, mission_id="OP-001", mission_name="Blackout",
        mission_status="ready",
        scheduled_at_utc=datetime.now(timezone.utc) + timedelta(hours=1),
        tz_name="UTC", created_by=1,
    )
    operation = await operations.mark_published(operation.id, channel_id=1, message_id=2)
    for user_id, name, status in signups:
        await operations.set_attendance(operation.id, user_id, name, status)
    await operations.transition(operation.id, OperationStatus.ACTIVE)
    operation = await operations.transition(operation.id, OperationStatus.COMPLETED)
    return operations, operation


async def test_finalization_creates_records_without_touching_signups(database):
    operations, operation = await completed_operation(
        database,
        signups=[(1, "Alpha", AttendanceStatus.ATTENDING), (2, "Bravo", AttendanceStatus.MAYBE)],
    )
    attendance = AttendanceService(database)
    await attendance.set_final_status(
        operation.id, 1, 1, "Alpha", FinalAttendance.ATTENDED, changed_by=99
    )
    await attendance.set_final_status(
        operation.id, 1, 2, "Bravo", FinalAttendance.ABSENT, changed_by=99
    )

    roster = await attendance.finalization_roster(operation.id)
    by_name = {entry.display_name: entry for entry in roster}
    assert by_name["Alpha"].final_status == "attended"
    assert by_name["Alpha"].signup_status == "attending"  # signup untouched
    assert by_name["Bravo"].final_status == "absent"

    # original signup rows still intact
    signup_roster = await operations.roster(operation.id)
    assert [r.user_id for r in signup_roster.attending] == [1]
    assert [r.user_id for r in signup_roster.maybe] == [2]


async def test_correction_writes_audit_trail(database):
    _, operation = await completed_operation(
        database, signups=[(1, "Alpha", AttendanceStatus.ATTENDING)]
    )
    attendance = AttendanceService(database)
    await attendance.set_final_status(
        operation.id, 1, 1, "Alpha", FinalAttendance.ABSENT, changed_by=99
    )
    await attendance.set_final_status(  # staff correction: actually attended
        operation.id, 1, 1, "Alpha", FinalAttendance.ATTENDED, changed_by=42
    )
    audits = await attendance.corrections(operation.id, 1, 1)
    assert [(a.previous_status, a.new_status, a.changed_by) for a in audits] == [
        (None, "absent", 99),
        ("absent", "attended", 42),
    ]


async def test_finalize_requires_active_or_completed(database):
    operations = OperationService(database)
    operation = await operations.create_operation(
        guild_id=1, mission_id="OP-001", mission_name="Blackout",
        mission_status="ready",
        scheduled_at_utc=datetime.now(timezone.utc) + timedelta(days=1),
        tz_name="UTC", created_by=1,
    )
    attendance = AttendanceService(database)
    with pytest.raises(ValidationError, match="operation is scheduled"):
        await attendance.set_final_status(
            operation.id, 1, 1, "Alpha", FinalAttendance.ATTENDED, changed_by=99
        )


async def test_bulk_finalize_marks_only_pending_signed_up(database):
    _, operation = await completed_operation(
        database,
        signups=[
            (1, "Alpha", AttendanceStatus.ATTENDING),
            (2, "Bravo", AttendanceStatus.ATTENDING),
            (3, "Charlie", AttendanceStatus.DECLINED),
        ],
    )
    attendance = AttendanceService(database)
    await attendance.set_final_status(  # pre-marked: bulk must not overwrite
        operation.id, 1, 1, "Alpha", FinalAttendance.EXCUSED, changed_by=99
    )
    written = await attendance.finalize_all_signed_up(operation.id, 1, changed_by=99)
    assert written == 1  # only Bravo (Alpha already judged, Charlie declined)

    roster = await attendance.finalization_roster(operation.id)
    by_name = {entry.display_name: entry for entry in roster}
    assert by_name["Alpha"].final_status == "excused"
    assert by_name["Bravo"].final_status == "attended"
    assert by_name["Charlie"].final_status is None


async def test_walk_on_gets_record_and_profile(database):
    _, operation = await completed_operation(database)
    attendance = AttendanceService(database)
    await attendance.set_final_status(
        operation.id, 1, 55, "WalkOn", FinalAttendance.ATTENDED, changed_by=99
    )
    player = await PlayerService(database).get(1, 55)
    assert player is not None  # profile auto-created
    roster = await attendance.finalization_roster(operation.id)
    assert any(e.display_name == "WalkOn" and e.signup_status is None for e in roster)


async def test_player_stats_math(database):
    attendance = AttendanceService(database)
    for index, verdict in enumerate(
        (FinalAttendance.ATTENDED, FinalAttendance.ATTENDED,
         FinalAttendance.ABSENT, FinalAttendance.EXCUSED)
    ):
        _, operation = await completed_operation(
            database, signups=[(1, "Alpha", AttendanceStatus.ATTENDING)]
        )
        await attendance.set_final_status(
            operation.id, 1, 1, "Alpha", verdict, changed_by=99
        )
    stats = await attendance.player_stats(1, 1)
    assert (stats.signups, stats.attended, stats.absent, stats.excused) == (4, 2, 1, 1)
    assert stats.rate == pytest.approx(66.7, abs=0.1)  # excused not counted against


async def test_unit_stats(database):
    attendance = AttendanceService(database)
    players = PlayerService(database)
    await players.get_or_create(1, 1, "Alpha")
    await players.get_or_create(1, 2, "Bravo")
    _, operation = await completed_operation(
        database,
        signups=[(1, "Alpha", AttendanceStatus.ATTENDING), (2, "Bravo", AttendanceStatus.ATTENDING)],
    )
    await attendance.finalize_all_signed_up(operation.id, 1, changed_by=99)

    stats = await attendance.unit_stats(1)
    assert stats.active_members == 2
    assert stats.operations_completed == 1
    assert stats.overall_attendance_rate == 100
    assert stats.most_attended == ("Blackout", 2)
    assert stats.largest_signup == ("Blackout", 2)


async def test_history_preserved_after_member_leaves(database):
    _, operation = await completed_operation(
        database, signups=[(1, "Alpha", AttendanceStatus.ATTENDING)]
    )
    attendance = AttendanceService(database)
    await attendance.set_final_status(
        operation.id, 1, 1, "Alpha", FinalAttendance.ATTENDED, changed_by=99
    )
    await PlayerService(database).mark_left(1, 1)

    stats = await attendance.player_stats(1, 1)
    assert stats.attended == 1  # history intact after leaving Discord
    roster = await attendance.finalization_roster(operation.id)
    assert any(e.display_name == "Alpha" for e in roster)
