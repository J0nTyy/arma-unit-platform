"""Self-service profile setup: role/experience/timezone selects + a modal
for bio and Steam ID. Everything optional, everything saved immediately."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from app.bot.views.components import respond_error
from app.bot.views.setup import COMMON_TIMEZONES
from app.database.models.player import EXPERIENCE_LEVELS, ROLE_PREFERENCES

if TYPE_CHECKING:
    from app.bot.bot import UnitBot

log = logging.getLogger(__name__)

_SKIP = "__skip__"


class ProfileSetupView(discord.ui.View):
    def __init__(self, bot: "UnitBot", member: discord.Member) -> None:
        super().__init__(timeout=900)
        self._bot = bot
        self._member = member

        def role_options(placeholder_none: str) -> list[discord.SelectOption]:
            options = [
                discord.SelectOption(label=label, value=slug)
                for slug, label in ROLE_PREFERENCES.items()
            ]
            options.append(discord.SelectOption(label=placeholder_none, value=_SKIP))
            return options

        self._primary = discord.ui.Select(
            placeholder="🎯 Primary role preference…", options=role_options("No preference"),
            row=0,
        )
        self._primary.callback = self._on_primary  # type: ignore[method-assign]
        self._secondary = discord.ui.Select(
            placeholder="🎯 Secondary role (optional)…", options=role_options("None"), row=1
        )
        self._secondary.callback = self._on_secondary  # type: ignore[method-assign]
        self._experience = discord.ui.Select(
            placeholder="🎖️ Your Arma experience…",
            options=[
                discord.SelectOption(label=label, value=slug)
                for slug, label in EXPERIENCE_LEVELS.items()
            ]
            + [discord.SelectOption(label="Prefer not to say", value=_SKIP)],
            row=2,
        )
        self._experience.callback = self._on_experience  # type: ignore[method-assign]
        self._timezone = discord.ui.Select(
            placeholder="🕒 Your timezone (optional)…",
            options=[discord.SelectOption(label=zone, value=zone) for zone in COMMON_TIMEZONES]
            + [discord.SelectOption(label="Skip", value=_SKIP)],
            row=3,
        )
        self._timezone.callback = self._on_timezone  # type: ignore[method-assign]
        for item in (self._primary, self._secondary, self._experience, self._timezone):
            self.add_item(item)

    async def _save(self, interaction: discord.Interaction, **fields) -> None:
        await self._bot.player_service.update_preferences(
            self._member.guild.id, self._member.id, self._member.display_name, **fields
        )
        await interaction.response.defer()

    async def _on_primary(self, interaction: discord.Interaction) -> None:
        try:
            value = self._primary.values[0]
            await self._save(interaction, primary_role=None if value == _SKIP else value)
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    async def _on_secondary(self, interaction: discord.Interaction) -> None:
        try:
            value = self._secondary.values[0]
            await self._save(interaction, secondary_role=None if value == _SKIP else value)
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    async def _on_experience(self, interaction: discord.Interaction) -> None:
        try:
            value = self._experience.values[0]
            await self._save(interaction, arma_experience=None if value == _SKIP else value)
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    async def _on_timezone(self, interaction: discord.Interaction) -> None:
        try:
            value = self._timezone.values[0]
            await self._save(interaction, timezone=None if value == _SKIP else value)
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    @discord.ui.button(label="Bio & Steam…", emoji="📝", style=discord.ButtonStyle.secondary, row=4)
    async def bio_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        try:
            player = await self._bot.player_service.get(
                self._member.guild.id, self._member.id
            )
            await interaction.response.send_modal(
                BioSteamModal(self._bot, self._member, player)
            )
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    @discord.ui.button(label="Done", emoji="✔️", style=discord.ButtonStyle.success, row=4)
    async def done(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(
            content="✅ Profile saved — check it with `/profile`.", view=None
        )


class BioSteamModal(discord.ui.Modal, title="Bio & Steam"):
    def __init__(self, bot: "UnitBot", member: discord.Member, player) -> None:
        super().__init__()
        self._bot = bot
        self._member = member
        self.bio_input = discord.ui.TextInput(
            label="Short bio (optional)",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=300,
            default=getattr(player, "bio", None) or "",
        )
        self.steam_input = discord.ui.TextInput(
            label="SteamID64 (optional, 17 digits)",
            required=False,
            max_length=20,
            placeholder="7656119…",
            default=getattr(player, "steam_id", None) or "",
        )
        self.add_item(self.bio_input)
        self.add_item(self.steam_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await self._bot.player_service.update_preferences(
                self._member.guild.id,
                self._member.id,
                self._member.display_name,
                bio=self.bio_input.value,
                steam_id=self.steam_input.value,
            )
            await interaction.response.send_message("📝 Saved.", ephemeral=True)
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)
