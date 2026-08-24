"""Reminder scheduling: due windows, restart-safety, per-guild toggle."""

from datetime import datetime, timedelta, timezone

from app.database.models.operation import AttendanceStatus
from app.services import GuildService
from app.services.operations import OperationService


async def published_operation(database, *, hours_ahead: float, guild_id: int = 1):
    service = OperationService(database)
    operation = await service.create_operation(
        guild_id=guild_id,
        mission_id="OP-001",
        mission_name="Blackout",
        mission_status="ready",
        scheduled_at_utc=datetime.now(timezone.utc) + timedelta(hours=hours_ahead),
        tz_name="UTC",
        created_by=100,
    )
    operation = await service.mark_published(operation.id, channel_id=5, message_id=6)
    return service, operation


async def test_24h_and_1h_reminders_fire_in_their_windows(database):
    service, operation = await published_operation(database, hours_ahead=30)
    await service.set_attendance(operation.id, 7, "Alpha", AttendanceStatus.ATTENDING)
    start = operation.scheduled_at.replace(tzinfo=timezone.utc)

    # too early — nothing due
    result = await service.tick(now=start - timedelta(hours=28))
    assert result.reminders == ()

    # inside the 24h window
    result = await service.tick(now=start - timedelta(hours=23))
    assert [r.kind for r in result.reminders] == ["24h"]
    assert result.reminders[0].attendee_ids == (7,)

    # 24h already sent; 1h fires inside its window
    result = await service.tick(now=start - timedelta(minutes=30))
    assert [r.kind for r in result.reminders] == ["1h"]


async def test_reminders_not_resent_and_survive_restart(database):
    service, operation = await published_operation(database, hours_ahead=30)
    start = operation.scheduled_at.replace(tzinfo=timezone.utc)
    when = start - timedelta(hours=23)

    assert len((await service.tick(now=when)).reminders) == 1
    assert (await service.tick(now=when)).reminders == ()

    # "restart": a brand-new service over the same database stays quiet
    restarted = OperationService(database)
    assert (await restarted.tick(now=when)).reminders == ()


async def test_last_minute_operation_skips_stale_24h_reminder(database):
    service, operation = await published_operation(database, hours_ahead=2)
    start = operation.scheduled_at.replace(tzinfo=timezone.utc)

    # created inside the 24h window -> that reminder is skipped, not sent late
    result = await service.tick(now=start - timedelta(hours=1, minutes=55))
    assert result.reminders == ()

    # but the 1h reminder still fires normally
    result = await service.tick(now=start - timedelta(minutes=45))
    assert [r.kind for r in result.reminders] == ["1h"]


async def test_reminders_respect_guild_toggle(database):
    await GuildService(database).update_settings(9, "Quiet Guild", reminders_enabled=False)
    service, operation = await published_operation(database, hours_ahead=30, guild_id=9)
    start = operation.scheduled_at.replace(tzinfo=timezone.utc)
    result = await service.tick(now=start - timedelta(hours=23))
    assert result.reminders == ()


async def test_operation_auto_activates_at_start_time(database):
    service, operation = await published_operation(database, hours_ahead=1)
    start = operation.scheduled_at.replace(tzinfo=timezone.utc)
    result = await service.tick(now=start + timedelta(minutes=1))
    assert [op.id for op in result.activated] == [operation.id]
    assert (await service.get(operation.id)).status == "active"


async def test_unpublished_operations_get_no_reminders(database):
    service = OperationService(database)
    operation = await service.create_operation(
        guild_id=1, mission_id="OP-001", mission_name="Blackout",
        mission_status="ready",
        scheduled_at_utc=datetime.now(timezone.utc) + timedelta(hours=30),
        tz_name="UTC", created_by=100,
    )
    start = operation.scheduled_at.replace(tzinfo=timezone.utc)
    result = await service.tick(now=start - timedelta(hours=23))
    assert result.reminders == ()  # scheduled-but-never-posted stays silent
