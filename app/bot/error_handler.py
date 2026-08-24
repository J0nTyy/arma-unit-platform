"""Centralized error handling for slash commands.

Users get a short, friendly, ephemeral message; full details go to the logs.
New error categories added in later phases (GitHub, AI, Arma) only need an
`AppError` subclass with a `user_message` — no handler changes required.
"""

from __future__ import annotations

import logging
import uuid

import discord
from discord import app_commands

from app.bot.permissions import PermissionDeniedError, TrainerOnlyError
from app.errors import (
    AppError,
    DatabaseError,
    ExternalServiceError,
    NotFoundError,
    ValidationError,
)

log = logging.getLogger(__name__)


def _command_name(interaction: discord.Interaction) -> str:
    return interaction.command.qualified_name if interaction.command else "<unknown>"


async def _respond(interaction: discord.Interaction, content: str) -> None:
    try:
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=True)
        else:
            await interaction.response.send_message(content, ephemeral=True)
    except discord.HTTPException:
        log.warning("Could not deliver error message for /%s", _command_name(interaction))


async def handle_app_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
) -> None:
    original: BaseException = error
    if isinstance(error, app_commands.CommandInvokeError):
        original = error.original

    command = _command_name(interaction)
    guild_id = interaction.guild.id if interaction.guild else None

    if isinstance(original, PermissionDeniedError):
        log.info(
            "Permission denied: /%s by user %s in guild %s (requires %s)",
            command, interaction.user.id, guild_id, original.required.name,
        )
        await _respond(
            interaction,
            f"🔒 This command requires **{original.required.name.title()}** access.",
        )
    elif isinstance(original, TrainerOnlyError):
        log.info("Trainer check failed: /%s by user %s", command, interaction.user.id)
        await _respond(
            interaction,
            "🔒 This needs the **Trainer** role (set in `/unit setup`) or staff access.",
        )
    elif isinstance(original, app_commands.CheckFailure):
        log.info("Check failed: /%s by user %s in guild %s", command, interaction.user.id, guild_id)
        await _respond(interaction, "🔒 You do not have permission to use this command.")
    elif isinstance(original, NotFoundError):
        log.info("Not found in /%s (guild %s): %s", command, guild_id, original)
        await _respond(interaction, f"❌ {original.user_message}")
    elif isinstance(original, ValidationError):
        await _respond(interaction, f"⚠️ {original.user_message}")
    elif isinstance(original, DatabaseError):
        log.error("Database error in /%s (guild %s)", command, guild_id, exc_info=original)
        await _respond(interaction, f"🗄️ {original.user_message}")
    elif isinstance(original, ExternalServiceError):
        log.error("External service error in /%s (guild %s)", command, guild_id, exc_info=original)
        await _respond(interaction, f"🌐 {original.user_message}")
    elif isinstance(original, AppError):
        log.error("Application error in /%s (guild %s)", command, guild_id, exc_info=original)
        await _respond(interaction, f"⚠️ {original.user_message}")
    else:
        # Unexpected — log with a reference ID users can quote when reporting.
        error_id = uuid.uuid4().hex[:8]
        log.error(
            "Unexpected error in /%s (guild %s, user %s) [ref %s]",
            command, guild_id, interaction.user.id, error_id,
            exc_info=original,
        )
        await _respond(
            interaction,
            f"❌ Something went wrong. The error has been logged (reference `{error_id}`).",
        )
