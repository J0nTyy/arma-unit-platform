"""Declarative permission levels for slash commands.

Usage::

    @app_commands.command()
    @require(PermissionLevel.ADMIN)
    async def some_command(self, interaction): ...

Checks always run server-side on every invocation — Discord-side
``default_permissions`` only controls UI visibility and is never trusted.

Phase 1 semantics (deliberately simple, to be replaced by database-driven
role configuration in a later phase):

- PUBLIC: anyone, anywhere (including DMs)
- MEMBER: any member of a guild the bot is in
- STAFF:  guild members with Manage Server (or Administrator)
- ADMIN:  guild members with Administrator
"""

from __future__ import annotations

import enum
from typing import Callable, TypeVar

import discord
from discord import app_commands

T = TypeVar("T")


class PermissionLevel(enum.IntEnum):
    PUBLIC = 0
    MEMBER = 1
    STAFF = 2
    ADMIN = 3


class PermissionDeniedError(app_commands.CheckFailure):
    """Raised when a user does not meet a command's permission level."""

    def __init__(self, required: PermissionLevel) -> None:
        self.required = required
        super().__init__(f"Command requires {required.name} access")


def _satisfies(interaction: discord.Interaction, level: PermissionLevel) -> bool:
    if level is PermissionLevel.PUBLIC:
        return True
    member = interaction.user
    if interaction.guild is None or not isinstance(member, discord.Member):
        return False
    if level is PermissionLevel.MEMBER:
        return True
    permissions = member.guild_permissions
    if level is PermissionLevel.STAFF:
        return permissions.manage_guild or permissions.administrator
    if level is PermissionLevel.ADMIN:
        return permissions.administrator
    return False


def require(level: PermissionLevel) -> Callable[[T], T]:
    """Gate an app command behind a permission level."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if _satisfies(interaction, level):
            return True
        raise PermissionDeniedError(level)

    def decorator(target: T) -> T:
        target = app_commands.check(predicate)(target)
        # Tag the required level so /help can display who may use the command.
        if isinstance(target, app_commands.Command):
            target.extras["permission_level"] = level
        else:  # raw coroutine — the Command created later keeps it as .callback
            target.__permission_level__ = level  # type: ignore[attr-defined]
        return target

    return decorator


def command_permission_level(command: app_commands.Command) -> PermissionLevel:
    """The permission level a command was tagged with (PUBLIC if untagged)."""
    level = command.extras.get("permission_level")
    if level is None:
        level = getattr(command.callback, "__permission_level__", PermissionLevel.PUBLIC)
    return level
