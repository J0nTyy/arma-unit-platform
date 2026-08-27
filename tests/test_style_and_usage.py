"""Style sampling (how the bot learns the room) and AI usage tracking."""

from datetime import date

from app.services.ai_usage import AIUsageService, estimate_cost_usd
from app.services.style_sampler import StyleSampler
from tests.test_assistant import bot as assistant_bot  # fixture re-export

bot = assistant_bot  # pytest fixture alias


# --- style sampler -------------------------------------------------------------


def test_sampler_collects_normal_chat_only():
    sampler = StyleSampler()
    ok = sampler.consider(1, "yeah saturday works for me", author_is_bot=False, staff_channel=False)
    assert ok
    # Everything below must be rejected:
    assert not sampler.consider(1, "lol", author_is_bot=False, staff_channel=False)  # too short
    assert not sampler.consider(1, "x" * 300, author_is_bot=False, staff_channel=False)  # too long
    assert not sampler.consider(1, "/mission list please", author_is_bot=False, staff_channel=False)
    assert not sampler.consider(1, "check https://example.com now", author_is_bot=False, staff_channel=False)
    assert not sampler.consider(1, "<@123> <@456> 👍", author_is_bot=False, staff_channel=False)
    assert not sampler.consider(1, "bot message text here", author_is_bot=True, staff_channel=False)
    assert not sampler.consider(1, "secret staff channel talk", author_is_bot=False, staff_channel=True)
    assert sampler.sample(1) == ["yeah saturday works for me"]


def test_sampler_is_guild_scoped_and_anonymous():
    sampler = StyleSampler()
    sampler.consider(1, "guild one message here", author_is_bot=False, staff_channel=False)
    sampler.consider(2, "guild two message here", author_is_bot=False, staff_channel=False)
    assert sampler.sample(2) == ["guild two message here"]
    assert sampler.sample(999) == []


def test_sampler_masks_mentions_and_caps_buffer():
    sampler = StyleSampler()
    sampler.consider(1, "ask <@1234567> about the op tonight", author_is_bot=False, staff_channel=False)
    assert sampler.sample(1) == ["ask @ about the op tonight"]  # no user IDs kept
    for index in range(100):
        sampler.consider(1, f"message number {index} about ops", author_is_bot=False, staff_channel=False)
    assert len(sampler.sample(1, count=100)) <= 40  # ring buffer cap


async def test_style_examples_reach_the_prompt(bot):
    from tests.test_assistant import REGISTRY, FakeAIChatClient, context_for
    from app.integrations.ai import AIResponse
    from app.services.assistant import AssistantService

    client = FakeAIChatClient([AIResponse(content="ok")])
    service = AssistantService(client, REGISTRY, personality="Persona.")
    await service.ask(
        context_for(bot), "hello",
        style_examples=["yo when we playing", "gg last night was rough"],
    )
    system = client.calls[0][0]["content"]
    assert "yo when we playing" in system
    assert "style reference ONLY" in system


# --- AI usage tracking ----------------------------------------------------------


async def test_usage_records_accumulate_per_day(database):
    service = AIUsageService(database)
    await service.record("openai", "gpt-5-mini", 100, 50)
    await service.record("openai", "gpt-5-mini", 200, 70)
    await service.record("openai", "gpt-5-mini", None, None)  # unknown counts

    summary = await service.summary()
    assert summary.total_requests == 3
    assert summary.total_input_tokens == 300
    assert summary.total_output_tokens == 120
    (row,) = summary.days
    assert row.day == date.today() and row.provider == "openai"
    # gpt-5-mini: $0.25/M in, $2/M out
    assert abs(summary.estimated_cost_usd - (300 * 0.25 + 120 * 2.0) / 1e6) < 1e-9


async def test_usage_unknown_model_gives_no_cost(database):
    service = AIUsageService(database)
    await service.record("gemini", "gemini-flash-latest", 1000, 500)
    summary = await service.summary()
    assert summary.total_requests == 1
    assert summary.estimated_cost_usd is None  # free tier / unknown price


def test_cost_estimation_prefix_matching():
    assert estimate_cost_usd("gpt-5-mini-2026-01", 1_000_000, 0) == 0.25
    assert estimate_cost_usd("gpt-5", 1_000_000, 0) == 1.25  # not caught by mini
    assert estimate_cost_usd("claude-opus-4-8", 0, 1_000_000) == 25.0
    assert estimate_cost_usd("some-unknown-model", 1000, 1000) is None


# --- developer gate --------------------------------------------------------------


async def test_is_developer_owner_role_and_denial(database):
    from types import SimpleNamespace

    from app.bot.permissions import is_developer
    from app.services import GuildService

    guild_service = GuildService(database)
    client = SimpleNamespace(guild_service=guild_service)
    guild = SimpleNamespace(id=1, owner_id=111)

    owner = SimpleNamespace(id=111, guild=guild, roles=[])
    staff_member = SimpleNamespace(id=222, guild=guild, roles=[SimpleNamespace(id=555)])

    # No role configured: only the server owner qualifies (staff does NOT).
    assert await is_developer(client, owner) is True
    assert await is_developer(client, staff_member) is False

    # Configured role grants access to its holders only.
    await guild_service.update_settings(1, "Guild", developer_role_id=777)
    developer = SimpleNamespace(id=333, guild=guild, roles=[SimpleNamespace(id=777)])
    assert await is_developer(client, developer) is True
    assert await is_developer(client, staff_member) is False