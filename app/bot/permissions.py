"""Declarative permission levels for slash commands and UI components.

Usage::

    @app_commands.command()
    @require(PermissionLevel.STAFF)
    async def some_command(self, interaction): ...

Checks always run server-side on every invocation — Discord-side
``default_permissions`` only controls UI visibility and is never trusted.
Interactive components (buttons, selects) re-check via
:func:`member_level` in their callbacks.

Level semantics:

- PUBLIC:        anyone, anywhere (including DMs)
- MEMBER:        any member of a guild the bot is in
- MISSION_MAKER: members holding the configured Mission Maker role
                 (set in /unit setup) — plus everyone who counts as STAFF
- STAFF:         members holding the configured Staff role; falls back to
                 Discord's Manage Server permission when no role is set
- ADMIN:         guild members with Administrator
"""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING, Callable, Iterable, TypeVar

import discord
from discord import app_commands

if TYPE_CHECKING:
    from app.database.models.guild import GuildConfiguration

T = TypeVar("T")


class PermissionLevel(enum.IntEnum):
    PUBLIC = 0
    MEMBER = 1
    MISSION_MAKER = 2
    STAFF = 3
    ADMIN = 4


class PermissionDeniedError(app_commands.CheckFailure):
    """Raised when a user does not meet a command's permission level."""

    def __init__(self, required: PermissionLevel) -> None:
        self.required = required
        super().__init__(f"Command requires {required.name} access")


def resolve_level(
    *,
    is_administrator: bool,
    has_manage_guild: bool,
    role_ids: Iterable[int],
    staff_role_id: int | None,
    mission_maker_role_id: int | None,
) -> PermissionLevel:
    """Pure permission-resolution logic (unit-testable without Discord)."""
    roles = set(role_ids)
    if is_administrator:
        return PermissionLevel.ADMIN
    if has_manage_guild or (staff_role_id is not None and staff_role_id in roles):
        return PermissionLevel.STAFF
    if mission_maker_role_id is not None and mission_maker_role_id in roles:
        return PermissionLevel.MISSION_MAKER
    return PermissionLevel.MEMBER


async def member_level(
    client: discord.Client, member: discord.Member | discord.User
) -> PermissionLevel:
    """Resolve a member's level, consulting the guild's configured roles."""
    if not isinstance(member, discord.Member):
        return PermissionLevel.PUBLIC
    configuration: "GuildConfiguration | None" = None
    guild_service = getattr(client, "guild_service", None)
    if guild_service is not None:
        configuration = await guild_service.get_configuration(member.guild.id)
    permissions = member.guild_permissions
    return resolve_level(
        is_administrator=permissions.administrator,
        has_manage_guild=permissions.manage_guild,
        role_ids=(role.id for role in member.roles),
        staff_role_id=configuration.staff_role_id if configuration else None,
        mission_maker_role_id=(
            configuration.mission_maker_role_id if configuration else None
        ),
    )


async def ensure_level(interaction: discord.Interaction, level: PermissionLevel) -> None:
    """Server-side check for component callbacks; raises PermissionDeniedError."""
    if level is PermissionLevel.PUBLIC:
        return
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        raise PermissionDeniedError(level)
    if level is PermissionLevel.MEMBER:
        return
    actual = await member_level(interaction.client, interaction.user)
    if actual < level:
        raise PermissionDeniedError(level)


def require(level: PermissionLevel) -> Callable[[T], T]:
    """Gate an app command behind a permission level."""

    async def predicate(interaction: discord.Interaction) -> bool:
        await ensure_level(interaction, level)
        return True

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
