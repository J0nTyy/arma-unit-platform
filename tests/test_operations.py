from datetime import datetime, timedelta, timezone

import pytest

from app.database.models.operation import OperationStatus
from app.errors import ValidationError
from app.services.operations import OperationNotFoundError, OperationService


def future(hours: float = 48) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


async def make_operation(database, **overrides):
    service = OperationService(database)
    defaults = dict(
        guild_id=1,
        mission_id="OP-001",
        mission_name="Blackout",
        mission_status="ready",
        scheduled_at_utc=future(),
        tz_name="Asia/Kolkata",
        created_by=100,
    )
    defaults.update(overrides)
    return service, await service.create_operation(**defaults)


async def test_create_operation(database):
    service, operation = await make_operation(database)
    assert operation.status == OperationStatus.SCHEDULED.value
    assert operation.max_players is None  # no member limit by default
    assert operation.name == "Blackout"
    assert operation.timezone == "Asia/Kolkata"


async def test_create_rejects_past_time(database):
    with pytest.raises(ValidationError, match="past"):
        await make_operation(database, scheduled_at_utc=future(hours=-1))


async def test_create_rejects_archived_mission(database):
    with pytest.raises(ValidationError, match="archived"):
        await make_operation(database, mission_status="archived")


async def test_create_allows_archived_when_staff_explicitly_permits(database):
    _, operation = await make_operation(
        database, mission_status="archived", allow_archived=True
    )
    assert operation.id is not None


async def test_lifecycle_happy_path(database):
    service, operation = await make_operation(database)
    operation = await service.mark_published(operation.id, channel_id=5, message_id=6)
    assert operation.status == OperationStatus.OPEN.value
    assert operation.message_id == 6
    operation = await service.transition(operation.id, OperationStatus.LOCKED)
    operation = await service.transition(operation.id, OperationStatus.OPEN)
    operation = await service.transition(operation.id, OperationStatus.ACTIVE)
    operation = await service.transition(operation.id, OperationStatus.COMPLETED)
    assert operation.status == OperationStatus.COMPLETED.value


@pytest.mark.parametrize(
    ("path", "invalid_next"),
    [
        ((), OperationStatus.ACTIVE),  # scheduled -> active skips open
        ((OperationStatus.OPEN, OperationStatus.ACTIVE, OperationStatus.COMPLETED),
         OperationStatus.OPEN),        # completed -> anything
        ((OperationStatus.CANCELLED,), OperationStatus.ACTIVE),  # cancelled -> active
        ((OperationStatus.CANCELLED,), OperationStatus.SCHEDULED),
    ],
)
async def test_invalid_transitions_rejected(database, path, invalid_next):
    service, operation = await make_operation(database)
    for step in path:
        operation = await service.transition(operation.id, step)
    with pytest.raises(ValidationError, match="invalid transition"):
        await service.transition(operation.id, invalid_next)


async def test_cancellation_from_any_active_state(database):
    service, operation = await make_operation(database)
    operation = await service.transition(operation.id, OperationStatus.OPEN)
    operation = await service.transition(operation.id, OperationStatus.CANCELLED)
    assert operation.status == OperationStatus.CANCELLED.value


async def test_reschedule_resets_reminders(database):
    service, operation = await make_operation(database)
    await service._update(  # simulate a sent reminder
        operation.id, reminder_24h_sent_at=datetime.now(timezone.utc)
    )
    operation = await service.reschedule(operation.id, future(hours=72))
    assert operation.reminder_24h_sent_at is None
    assert operation.reminder_1h_sent_at is None


async def test_reschedule_rejects_past(database):
    service, operation = await make_operation(database)
    with pytest.raises(ValidationError, match="past"):
        await service.reschedule(operation.id, future(hours=-2))


async def test_discard_unpublished(database):
    service, operation = await make_operation(database)
    await service.discard_unpublished(operation.id)
    with pytest.raises(OperationNotFoundError):
        await service.get(operation.id)


async def test_discard_refuses_published(database):
    service, operation = await make_operation(database)
    await service.mark_published(operation.id, channel_id=5, message_id=6)
    with pytest.raises(ValidationError, match="already published"):
        await service.discard_unpublished(operation.id)


async def test_list_upcoming_excludes_terminal(database):
    service, first = await make_operation(database)
    _, second = await make_operation(database, mission_id="OP-002", mission_name="Iron Rain")
    await service.transition(first.id, OperationStatus.CANCELLED)
    upcoming = await service.list_upcoming(1)
    assert [op.id for op in upcoming] == [second.id]


def test_parse_local_datetime_converts_to_utc(database):
    service = OperationService(database)
    when = service.parse_local_datetime("05/09/2026", "20:00", "Asia/Kolkata")
    assert when.tzinfo is timezone.utc
    assert (when.hour, when.minute) == (14, 30)  # IST is UTC+5:30
    iso = service.parse_local_datetime("2026-09-05", "20:00", "Asia/Kolkata")
    assert iso == when


def test_parse_local_datetime_rejects_garbage(database):
    service = OperationService(database)
    with pytest.raises(ValidationError, match="date"):
        service.parse_local_datetime("Saturday", "20:00", "UTC")
    with pytest.raises(ValidationError, match="time"):
        service.parse_local_datetime("05/09/2026", "8pm", "UTC")
    with pytest.raises(ValidationError):
        service.parse_local_datetime("05/09/2026", "20:00", "Not/AZone")
