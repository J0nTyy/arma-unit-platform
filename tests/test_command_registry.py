"""Registry-level checks on the Discord command tree.

Builds the real bot (without connecting to Discord) and asserts invariants:
every command is described for Discord users, carries a permission check,
and /help can classify it.
"""

import discord
import pytest
from discord import app_commands

from app.bot.bot import EXTENSIONS, UnitBot
from app.bot.permissions import PermissionLevel, command_permission_level
from app.config import Settings


def walk_commands(bot: UnitBot):
    for top in bot.tree.get_commands():
        if isinstance(top, app_commands.Group):
            yield from (c for c in top.commands if isinstance(c, app_commands.Command))
        elif isinstance(top, app_commands.Command):
            yield top


@pytest.fixture
async def bot(database, monkeypatch):
    for var in ("GITHUB_MISSIONS_OWNER", "GITHUB_MISSIONS_REPOSITORY", "GITHUB_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    settings = Settings(
        _env_file=None,
        discord_token="test-token",
        discord_application_id=1,
        database_url="sqlite+aiosqlite:///:memory:",
    )
    bot = UnitBot(settings, database)
    for extension in EXTENSIONS:
        await bot.load_extension(extension)
    yield bot
    await bot.close()


async def test_expected_commands_registered(bot):
    top_level = sorted(c.name for c in bot.tree.get_commands())
    assert top_level == [
        "about", "help", "mission", "missions",
        "operation", "operations", "ping", "profile", "unit",
    ]

    mission = bot.tree.get_command("mission")
    assert sorted(c.name for c in mission.commands) == ["publish", "view"]
    operation = bot.tree.get_command("operation")
    assert sorted(c.name for c in operation.commands) == ["create", "manage", "view"]
    unit = bot.tree.get_command("unit")
    assert sorted(c.name for c in unit.commands) == ["diagnostics", "setup", "sync"]


async def test_every_command_has_a_description(bot):
    for command in walk_commands(bot):
        assert command.description.strip(), f"/{command.qualified_name} has no description"
        assert command.description != "…", f"/{command.qualified_name} has a placeholder description"
        for parameter in command.parameters:
            assert parameter.description.strip() != "…", (
                f"/{command.qualified_name} parameter '{parameter.name}' is undescribed"
            )


async def test_every_command_has_a_permission_check(bot):
    for command in walk_commands(bot):
        assert command.checks, f"/{command.qualified_name} has no permission check"


async def test_permission_levels_are_tagged_correctly(bot):
    levels = {
        command.qualified_name: command_permission_level(command)
        for command in walk_commands(bot)
    }
    assert levels["ping"] is PermissionLevel.PUBLIC
    assert levels["help"] is PermissionLevel.PUBLIC
    assert levels["missions"] is PermissionLevel.MEMBER
    assert levels["profile"] is PermissionLevel.MEMBER
    assert levels["operations"] is PermissionLevel.MEMBER
    assert levels["mission publish"] is PermissionLevel.MISSION_MAKER
    assert levels["operation create"] is PermissionLevel.MISSION_MAKER
    assert levels["operation manage"] is PermissionLevel.STAFF
    assert levels["unit sync"] is PermissionLevel.STAFF
    assert levels["unit setup"] is PermissionLevel.ADMIN


async def test_staff_group_hidden_from_members_in_ui(bot):
    unit = bot.tree.get_command("unit")
    assert unit.default_permissions is not None
    assert unit.default_permissions.manage_guild


async def test_bot_reports_missions_unconfigured(bot):
    # No GITHUB_MISSIONS_* in test settings -> service disabled, not crashing.
    assert bot.mission_service is None
    assert bot.github_client is None