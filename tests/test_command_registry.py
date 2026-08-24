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
    assert top_level == ["about", "config", "help", "mission", "ping", "status"]

    mission = bot.tree.get_command("mission")
    assert sorted(c.name for c in mission.commands) == [
        "brief", "list", "search", "sync", "validate", "view",
    ]


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
    assert levels["mission list"] is PermissionLevel.MEMBER
    assert levels["mission sync"] is PermissionLevel.STAFF
    assert levels["config setup"] is PermissionLevel.ADMIN


async def test_admin_group_hidden_from_non_admins_in_ui(bot):
    config = bot.tree.get_command("config")
    assert config.default_permissions is not None
    assert config.default_permissions.administrator


async def test_bot_reports_missions_unconfigured(bot):
    # No GITHUB_MISSIONS_* in test settings -> service disabled, not crashing.
    assert bot.mission_service is None
    assert bot.github_client is None