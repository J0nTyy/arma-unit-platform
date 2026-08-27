"""AI assistant: tool authorization, the tool loop, rate limiting, memory.

No real AI provider is used anywhere — the model is a scripted fake, and the
tools run against real services over SQLite.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.bot.permissions import PermissionLevel
from app.database.models.operation import AttendanceStatus
from app.errors import AIIntegrationError, RateLimitedError
from app.integrations.ai import AIResponse, ToolCall
from app.services import (
    AttendanceService,
    GuildService,
    KnowledgeService,
    MemoryService,
    MissionService,
    OperationService,
    PlayerService,
)
from app.services.assistant import AssistantService, RateLimiter, load_personality
from app.services.assistant_tools import ToolContext, build_default_registry
from tests.test_knowledge import write_unit_files
from tests.test_mission_service import FakeGitHubClient, mission_files


@pytest.fixture
async def bot(database, tmp_path):
    """A duck-typed bot with real services over SQLite, fake GitHub for
    missions, and a real (temporary) unit/ directory for knowledge."""
    github = FakeGitHubClient(
        mission_files("OP-002", name="Operation Iron Rain", map="Livonia")
    )
    bot = SimpleNamespace(
        guild_service=GuildService(database),
        mission_service=MissionService(database, github),
        knowledge_service=KnowledgeService(database, write_unit_files(tmp_path)),
        operation_service=OperationService(database),
        player_service=PlayerService(database),
        attendance_service=AttendanceService(database),
        memory_service=MemoryService(database),
        assistant_service=None,
    )
    await bot.mission_service.sync()
    await bot.knowledge_service.sync()
    await bot.guild_service.update_settings(1, "Guild", unit_name="42nd Test", timezone="UTC")
    return bot


def context_for(bot, level=PermissionLevel.MEMBER) -> ToolContext:
    return ToolContext(bot=bot, guild_id=1, user_id=7, level=level)


REGISTRY = build_default_registry()


# --- tool authorization and behavior ------------------------------------------


async def test_tools_hidden_and_denied_below_member(bot):
    assert REGISTRY.specs_for(PermissionLevel.PUBLIC) == []
    result = await REGISTRY.execute(
        "search_missions", "{}", context_for(bot, PermissionLevel.PUBLIC)
    )
    assert "not authorized" in result


async def test_unknown_tool_and_malformed_arguments(bot):
    context = context_for(bot)
    assert "unknown tool" in await REGISTRY.execute("drop_tables", "{}", context)
    assert "malformed" in await REGISTRY.execute("search_missions", "{not json", context)


async def test_search_and_get_mission_tools(bot):
    context = context_for(bot)
    found = await REGISTRY.execute("search_missions", json.dumps({"query": "iron"}), context)
    assert "OP-002" in found and "Iron Rain" in found
    detail = await REGISTRY.execute("get_mission", json.dumps({"mission_id": "op-002"}), context)
    assert "Livonia" in detail
    missing = await REGISTRY.execute("get_mission", json.dumps({"mission_id": "OP-404"}), context)
    assert "No mission with ID" in missing


async def test_knowledge_tool_respects_requester_level(bot):
    member_result = await REGISTRY.execute(
        "search_knowledge", json.dumps({"query": "staff doc setup"}), context_for(bot)
    )
    assert "Staff Doc" not in member_result
    staff_result = await REGISTRY.execute(
        "search_knowledge",
        json.dumps({"query": "staff doc setup"}),
        context_for(bot, PermissionLevel.STAFF),
    )
    assert "Staff Doc" in staff_result


async def test_operation_and_roster_tools(bot):
    operation = await bot.operation_service.create_operation(
        guild_id=1, mission_id="OP-002", mission_name="Operation Iron Rain",
        mission_status="ready",
        scheduled_at_utc=datetime.now(timezone.utc) + timedelta(days=2),
        tz_name="UTC", created_by=1,
    )
    await bot.operation_service.mark_published(operation.id, channel_id=1, message_id=2)
    await bot.operation_service.set_attendance(operation.id, 11, "Alpha", AttendanceStatus.ATTENDING)
    await bot.operation_service.set_attendance(operation.id, 12, "Bravo", AttendanceStatus.DECLINED)

    upcoming = await REGISTRY.execute("get_upcoming_operations", "{}", context_for(bot))
    assert "Iron Rain" in upcoming and "1 attending" in upcoming

    args = json.dumps({"operation_id": operation.id})
    member_roster = await REGISTRY.execute("get_operation_roster", args, context_for(bot))
    assert "Alpha" in member_roster
    assert "Bravo" not in member_roster  # members see declined count, not names
    staff_roster = await REGISTRY.execute(
        "get_operation_roster", args, context_for(bot, PermissionLevel.STAFF)
    )
    assert "Bravo" in staff_roster


async def test_my_profile_tool_returns_own_private_data(bot):
    await bot.player_service.update_preferences(
        1, 7, "Asker", primary_role="medic", timezone="Asia/Kolkata"
    )
    result = await REGISTRY.execute("get_my_profile", "{}", context_for(bot))
    assert "Medic" in result and "Asia/Kolkata" in result and "Participation" in result


async def test_member_profile_tool_hides_participation_from_members(bot):
    await bot.player_service.update_preferences(1, 42, "Kartikey", primary_role="infantry")
    result = await REGISTRY.execute(
        "get_member_profile", json.dumps({"name": "Kartikey"}), context_for(bot)
    )
    assert "Infantry" in result
    assert "Participation" not in result or "private" in result  # minimal visibility
    assert "private" in result

    staff_result = await REGISTRY.execute(
        "get_member_profile", json.dumps({"name": "Kartikey"}),
        context_for(bot, PermissionLevel.STAFF),
    )
    assert "[staff] Participation" in staff_result


async def test_member_profile_tool_guild_isolation(bot):
    await bot.player_service.get_or_create(2, 500, "OtherGuildGuy")
    result = await REGISTRY.execute(
        "get_member_profile", json.dumps({"name": "OtherGuildGuy"}), context_for(bot)
    )
    assert "No unit member matches" in result  # other guild's members invisible


async def test_attendance_leaders_is_staff_only(bot):
    denied = await REGISTRY.execute("get_attendance_leaders", "{}", context_for(bot))
    assert "not authorized" in denied
    allowed = await REGISTRY.execute(
        "get_attendance_leaders", "{}", context_for(bot, PermissionLevel.STAFF)
    )
    assert "not authorized" not in allowed
    # ...and members never even see it in their tool list
    member_tools = {t["function"]["name"] for t in REGISTRY.specs_for(PermissionLevel.MEMBER)}
    assert "get_attendance_leaders" not in member_tools


async def test_tool_handler_failure_is_contained(bot):
    bot.mission_service = None  # simulate unconfigured integration
    result = await REGISTRY.execute("search_missions", "{}", context_for(bot))
    assert "not configured" in result


# --- assistant service ------------------------------------------------------------


class FakeAIChatClient:
    """Scripted model: pops one AIResponse per chat() call, records inputs."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[list[dict]] = []
        self.model = "fake-model"

    async def chat(self, messages, tools=None):
        self.calls.append([dict(m) for m in messages])
        if isinstance(self.responses[0], Exception):
            raise self.responses.pop(0)
        return self.responses.pop(0)


def make_service(client, per_minute=10):
    return AssistantService(
        client, REGISTRY, personality="You are a test assistant.",
        requests_per_minute=per_minute,
    )


def tool_call_response(name, **arguments):
    call = ToolCall(id="call_1", name=name, arguments_json=json.dumps(arguments))
    return AIResponse(
        content=None, tool_calls=(call,),
        raw_message={"role": "assistant", "tool_calls": [
            {"id": "call_1", "type": "function",
             "function": {"name": name, "arguments": json.dumps(arguments)}}]},
    )


async def test_ask_runs_tools_and_returns_grounded_answer(bot):
    client = FakeAIChatClient([
        tool_call_response("search_missions", query="iron rain"),
        AIResponse(content="Iron Rain is a Defense mission on Livonia."),
    ])
    service = make_service(client)
    answer = await service.ask(context_for(bot), "Tell me about Iron Rain")
    assert "Livonia" in answer
    # second call must contain the tool result for grounding
    tool_messages = [m for m in client.calls[1] if m.get("role") == "tool"]
    assert tool_messages and "OP-002" in tool_messages[0]["content"]


async def test_follow_up_gets_conversation_memory(bot):
    client = FakeAIChatClient([
        AIResponse(content="Iron Rain, Saturday 20:00."),
        AIResponse(content="Livonia."),
    ])
    service = make_service(client)
    await service.ask(context_for(bot), "What's our next operation?")
    await service.ask(context_for(bot), "What map?")
    remembered = [m["content"] for m in client.calls[1] if m["role"] == "assistant"]
    assert "Iron Rain, Saturday 20:00." in remembered


async def test_rate_limit_enforced(bot):
    client = FakeAIChatClient([AIResponse(content="ok")] * 5)
    service = make_service(client, per_minute=2)
    await service.ask(context_for(bot), "one")
    await service.ask(context_for(bot), "two")
    with pytest.raises(RateLimitedError):
        await service.ask(context_for(bot), "three")


async def test_provider_failure_propagates_cleanly(bot):
    client = FakeAIChatClient([AIIntegrationError("provider unreachable")])
    service = make_service(client)
    with pytest.raises(AIIntegrationError) as info:
        await service.ask(context_for(bot), "hello?")
    assert "temporarily unavailable" in info.value.user_message


async def test_endless_tool_calls_end_in_clean_error(bot):
    client = FakeAIChatClient([tool_call_response("get_upcoming_operations")] * 10)
    service = make_service(client)
    with pytest.raises(AIIntegrationError):
        await service.ask(context_for(bot), "loop forever")


async def test_empty_question_short_circuits(bot):
    client = FakeAIChatClient([])
    service = make_service(client)
    answer = await service.ask(context_for(bot), "   ")
    assert "Ask me" in answer and client.calls == []


def test_rate_limiter_window():
    limiter = RateLimiter(per_minute=1)
    limiter.check(1)
    with pytest.raises(RateLimitedError):
        limiter.check(1)
    limiter.check(2)  # other users unaffected


def test_personality_loads_from_file_and_falls_back(tmp_path):
    path = tmp_path / "personality.md"
    path.write_text("Be excellent.", encoding="utf-8")
    assert load_personality(str(path)) == "Be excellent."
    # A missing file falls back to the shipped template (repo-relative).
    fallback = load_personality(str(tmp_path / "missing.md"))
    template = Path("templates/unit/personality/personality.example.md")
    assert fallback == template.read_text(encoding="utf-8").strip()


def test_real_personality_file_present():
    personality = load_personality("unit/personality/personality.md")
    assert "Grounding rules" in personality  # the real file, not the fallback
