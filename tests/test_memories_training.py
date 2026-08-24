"""Server memory, cert eligibility, and the new assistant context features."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.bot.permissions import PermissionLevel
from app.database.models.operation import AttendanceStatus, OperationStatus
from app.database.models.player import FinalAttendance
from app.services import (
    AttendanceService,
    MemoryService,
    OperationService,
    PlayerService,
)
from app.services.assistant_tools import ToolContext
from tests.test_assistant import (
    REGISTRY,
    FakeAIChatClient,
    context_for,
    make_service,
    bot as assistant_bot,  # fixture re-export
)
from app.integrations.ai import AIResponse

bot = assistant_bot  # pytest fixture alias


# --- server memory -----------------------------------------------------------------


async def test_remember_and_recall(database):
    service = MemoryService(database)
    await service.remember(1, "Op nights moved to Fridays at 2000", author_id=7)
    await service.remember(1, "Vector is the unit's armor specialist", author_id=8)
    await service.remember(2, "Other guild fact about Fridays", author_id=9)

    hits = await service.recall(1, "when are op nights?")
    assert len(hits) == 1 and "Fridays" in hits[0].content  # guild-scoped

    assert await service.recall(1, "zeppelin maintenance") == []
    assert await service.count(1) == 2


async def test_forget_memory(database):
    service = MemoryService(database)
    memory = await service.remember(1, "A fact that turns out to be wrong", author_id=7)
    assert await service.forget(1, memory.id) is True
    assert await service.forget(1, memory.id) is False  # already gone
    assert await service.forget(2, memory.id) is False  # never cross-guild


async def test_memory_cap_drops_oldest(database, monkeypatch):
    import app.services.memories as memories_module

    monkeypatch.setattr(memories_module, "_MAX_MEMORIES_PER_GUILD", 3)
    service = MemoryService(database)
    for index in range(5):
        await service.remember(1, f"fact number {index} about the unit", author_id=7)
    assert await service.count(1) == 3
    remaining = await service.list_recent(1)
    assert all("number 0" not in m.content and "number 1" not in m.content for m in remaining)


async def test_save_memory_tool(bot):
    result = await REGISTRY.execute(
        "save_memory",
        json.dumps({"fact": "The unit runs joint ops with 3rd MEU monthly"}),
        context_for(bot),
    )
    assert "saved" in result.lower()
    hits = await bot.memory_service.recall(1, "joint ops 3rd MEU")
    assert hits and hits[0].author_id == 7

    too_short = await REGISTRY.execute(
        "save_memory", json.dumps({"fact": "hi"}), context_for(bot)
    )
    assert "Error" in too_short


async def test_memories_injected_into_system_prompt(bot):
    await bot.memory_service.remember(1, "Op nights are Fridays at 2000", author_id=7)
    client = FakeAIChatClient([AIResponse(content="Fridays at 2000.")])
    service = make_service(client)
    await service.ask(context_for(bot), "when do we usually run ops?")
    system = client.calls[0][0]["content"]
    assert "Server memory" in system and "Fridays at 2000" in system


# --- command guide tool ---------------------------------------------------------------


async def test_command_guide_hides_staff_section_from_members(bot):
    member_guide = await REGISTRY.execute("get_command_guide", "{}", context_for(bot))
    assert "/training certs" in member_guide
    assert "/unit setup" not in member_guide
    staff_guide = await REGISTRY.execute(
        "get_command_guide", "{}", context_for(bot, PermissionLevel.STAFF)
    )
    assert "/unit setup" in staff_guide


# --- assistant context plumbing ---------------------------------------------------------


async def test_chat_context_and_staff_location_in_prompt(bot):
    client = FakeAIChatClient([AIResponse(content="ok")])
    service = make_service(client)
    await service.ask(
        context_for(bot, PermissionLevel.STAFF),
        "who was complaining about mods?",
        chat_context="Alpha: my mods broke again\nBravo: classic Alpha",
        staff_channel=True,
    )
    system = client.calls[0][0]["content"]
    assert "my mods broke again" in system
    assert "STAFF-ONLY channel" in system


async def test_public_location_note_for_staff_in_public_channel(bot):
    client = FakeAIChatClient([AIResponse(content="ok")])
    service = make_service(client)
    await service.ask(
        context_for(bot, PermissionLevel.STAFF), "hello", staff_channel=False
    )
    assert "Do not surface staff-only details" in client.calls[0][0]["content"]


async def test_quoted_message_reaches_the_model(bot):
    client = FakeAIChatClient([AIResponse(content="nice one")])
    service = make_service(client)
    await service.ask(
        context_for(bot), "thoughts?",
        quoted='Alpha: "just got my medic cert!"',
    )
    user_message = client.calls[0][-1]["content"]
    assert "medic cert" in user_message and "thoughts?" in user_message


async def test_chatter_generates_or_skips(bot):
    client = FakeAIChatClient([
        AIResponse(content="Somebody buy Alpha a compass already."),
        AIResponse(content="SKIP"),
    ])
    service = make_service(client)
    text = await service.chatter("Alpha: got lost again\nBravo: lol", "42nd")
    assert text == "Somebody buy Alpha a compass already."
    assert await service.chatter("quiet channel", "42nd") is None


# --- cert eligibility ---------------------------------------------------------------


async def make_attended_ops(database, user_id: int, count: int) -> None:
    operations = OperationService(database)
    attendance = AttendanceService(database)
    for _ in range(count):
        operation = await operations.create_operation(
            guild_id=1, mission_id="OP-001", mission_name="Blackout",
            mission_status="ready",
            scheduled_at_utc=datetime.now(timezone.utc) + timedelta(hours=1),
            tz_name="UTC", created_by=1,
        )
        await operations.mark_published(operation.id, channel_id=1, message_id=2)
        await operations.set_attendance(operation.id, user_id, "K", AttendanceStatus.ATTENDING)
        await operations.transition(operation.id, OperationStatus.ACTIVE)
        await operations.transition(operation.id, OperationStatus.COMPLETED)
        await attendance.set_final_status(
            operation.id, 1, user_id, "K", FinalAttendance.ATTENDED, changed_by=99
        )


async def test_cert_eligibility_progression(database):
    players = PlayerService(database)
    await players.get_or_create(1, 100, "K")

    by_cert = {s.cert: s for s in await players.cert_eligibility(1, 100)}
    assert not by_cert["medic"].eligible  # 0 ops attended
    assert "attend 2 more" in by_cert["medic"].missing[0]

    await make_attended_ops(database, 100, 3)
    by_cert = {s.cert: s for s in await players.cert_eligibility(1, 100)}
    assert by_cert["medic"].eligible
    assert by_cert["eod"].eligible is False  # 3 ops but needs engineer cert
    assert any("Engineer" in reason for reason in by_cert["eod"].missing)

    await players.grant_qualification(1, 100, "engineer", granted_by=9)
    by_cert = {s.cert: s for s in await players.cert_eligibility(1, 100)}
    assert by_cert["eod"].eligible
    assert by_cert["engineer"].held
