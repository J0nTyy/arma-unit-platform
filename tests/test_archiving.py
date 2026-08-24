"""Archiving lifecycle: completed ops log immediately, cancelled after 24h."""

from datetime import datetime, timedelta, timezone

from app.database.models.operation import OperationStatus
from app.services.operations import OperationService


async def published_operation(database):
    service = OperationService(database)
    operation = await service.create_operation(
        guild_id=1,
        mission_id="OP-001",
        mission_name="Blackout",
        mission_status="ready",
        scheduled_at_utc=datetime.now(timezone.utc) + timedelta(hours=30),
        tz_name="UTC",
        created_by=100,
    )
    return service, await service.mark_published(operation.id, channel_id=5, message_id=6)


async def test_completed_operation_archives_immediately(database):
    service, operation = await published_operation(database)
    await service.transition(operation.id, OperationStatus.ACTIVE)
    await service.transition(operation.id, OperationStatus.COMPLETED)
    result = await service.tick()
    assert [op.id for op in result.to_archive] == [operation.id]


async def test_cancelled_operation_waits_24h_before_archiving(database):
    service, operation = await published_operation(database)
    operation = await service.transition(operation.id, OperationStatus.CANCELLED)
    assert operation.cancelled_at is not None

    now = datetime.now(timezone.utc)
    result = await service.tick(now=now + timedelta(hours=23))
    assert result.to_archive == ()  # still in its 24h grace window
    result = await service.tick(now=now + timedelta(hours=25))
    assert [op.id for op in result.to_archive] == [operation.id]


async def test_archived_operations_are_not_reprocessed(database):
    service, operation = await published_operation(database)
    await service.transition(operation.id, OperationStatus.ACTIVE)
    await service.transition(operation.id, OperationStatus.COMPLETED)
    assert len((await service.tick()).to_archive) == 1
    await service.mark_archived(operation.id)
    assert (await service.tick()).to_archive == ()

    # restart-safety: a fresh service over the same DB stays quiet too
    assert (await OperationService(database).tick()).to_archive == ()


async def test_unpublished_operations_never_archive(database):
    service = OperationService(database)
    operation = await service.create_operation(
        guild_id=1, mission_id="OP-001", mission_name="Blackout",
        mission_status="ready",
        scheduled_at_utc=datetime.now(timezone.utc) + timedelta(hours=30),
        tz_name="UTC", created_by=100,
    )
    await service.transition(operation.id, OperationStatus.CANCELLED)
    result = await service.tick(now=datetime.now(timezone.utc) + timedelta(days=3))
    assert result.to_archive == ()


async def test_brief_message_tracking(database):
    service, operation = await published_operation(database)
    operation = await service.set_brief_messages(operation.id, channel_id=9, message_ids=[11, 12])
    assert operation.brief_channel_id == 9
    assert operation.brief_message_ids == [11, 12]
