"""Staff member management panel: pick a member, then manage status,
onboarding and qualifications from one interactive card."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from app.bot import embeds
from app.bot.permissions import PermissionLevel, ensure_level
from app.bot.views.components import respond_error
from app.database.models.player import QUALIFICATIONS, MemberStatus

if TYPE_CHECKING:
    from app.bot.bot import UnitBot

log = logging.getLogger(__name__)


async def build_member_panel(bot: "UnitBot", guild_id: int, user_id: int, display_name: str):
    """(embed, view) for one member, staff perspective."""
    player = await bot.player_service.get_or_create(guild_id, user_id, display_name)
    qualifications = await bot.player_service.qualifications(player.id)
    stats = await bot.attendance_service.player_stats(guild_id, user_id)
    history = await bot.attendance_service.recent_history(guild_id, user_id)
    embed = embeds.profile_embed(
        player, qualifications, stats=stats, history=history, viewer="staff"
    )
    return embed, MemberPanelView(bot, guild_id, user_id, display_name, player, qualifications)


class MemberPickView(discord.ui.View):
    """Entry point for /members — native Discord user picker."""

    def __init__(self, bot: "UnitBot") -> None:
        super().__init__(timeout=600)
        self._bot = bot
        picker = discord.ui.UserSelect(placeholder="Pick a member to manage…")
        picker.callback = self._on_pick  # type: ignore[method-assign]
        self._picker = picker
        self.add_item(picker)

    async def _on_pick(self, interaction: discord.Interaction) -> None:
        try:
            await ensure_level(interaction, PermissionLevel.STAFF)
            user = self._picker.values[0]
            if user.bot:
                await interaction.response.send_message("🤖 That's a bot.", ephemeral=True)
                return
            display = user.display_name if hasattr(user, "display_name") else user.name
            embed, view = await build_member_panel(
                self._bot, interaction.guild.id, user.id, display  # type: ignore[union-attr]
            )
            await interaction.response.edit_message(content=None, embed=embed, view=view)
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)


class MemberPanelView(discord.ui.View):
    def __init__(
        self, bot: "UnitBot", guild_id: int, user_id: int, display_name: str,
        player, qualifications,
    ) -> None:
        super().__init__(timeout=600)
        self._bot = bot
        self._guild_id = guild_id
        self._user_id = user_id
        self._display_name = display_name

        status_select = discord.ui.Select(
            placeholder="Set member status…",
            options=[
                discord.SelectOption(
                    label=embeds.MEMBER_STATUS_BADGE[status.value],
                    value=status.value,
                    default=player.active_status == status.value,
                )
                for status in MemberStatus
            ],
            row=0,
        )
        status_select.callback = self._on_status  # type: ignore[method-assign]
        self._status_select = status_select
        self.add_item(status_select)

        held = {q.qualification for q in qualifications}
        grantable = [
            discord.SelectOption(label=label, value=slug)
            for slug, label in QUALIFICATIONS.items()
            if slug not in held
        ]
        if grantable:
            grant = discord.ui.Select(
                placeholder="🏅 Grant qualification…", options=grantable, row=1
            )
            grant.callback = self._on_grant  # type: ignore[method-assign]
            self._grant = grant
            self.add_item(grant)
        if held:
            revoke = discord.ui.Select(
                placeholder="❌ Revoke qualification…",
                options=[
                    discord.SelectOption(label=QUALIFICATIONS.get(slug, slug), value=slug)
                    for slug in sorted(held)
                ],
                row=2,
            )
            revoke.callback = self._on_revoke  # type: ignore[method-assign]
            self._revoke = revoke
            self.add_item(revoke)

        self._onboarding_next = (
            "complete" if player.onboarding_status != "complete" else "incomplete"
        )
        onboarding = discord.ui.Button(
            label=(
                "Mark onboarding complete"
                if self._onboarding_next == "complete"
                else "Mark onboarding incomplete"
            ),
            emoji="🎓", style=discord.ButtonStyle.secondary, row=3,
        )
        onboarding.callback = self._on_onboarding  # type: ignore[method-assign]
        self.add_item(onboarding)

        back = discord.ui.Button(label="Pick another member", emoji="↩️",
                                 style=discord.ButtonStyle.secondary, row=3)
        back.callback = self._on_back  # type: ignore[method-assign]
        self.add_item(back)

    async def _refresh(self, interaction: discord.Interaction) -> None:
        embed, view = await build_member_panel(
            self._bot, self._guild_id, self._user_id, self._display_name
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def _on_status(self, interaction: discord.Interaction) -> None:
        try:
            await ensure_level(interaction, PermissionLevel.STAFF)
            await self._bot.player_service.set_status(
                self._guild_id, self._user_id, self._status_select.values[0]
            )
            await self._refresh(interaction)
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    async def _on_grant(self, interaction: discord.Interaction) -> None:
        try:
            await ensure_level(interaction, PermissionLevel.STAFF)
            await self._bot.player_service.grant_qualification(
                self._guild_id, self._user_id, self._grant.values[0], interaction.user.id
            )
            await self._refresh(interaction)
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    async def _on_revoke(self, interaction: discord.Interaction) -> None:
        try:
            await ensure_level(interaction, PermissionLevel.STAFF)
            await self._bot.player_service.revoke_qualification(
                self._guild_id, self._user_id, self._revoke.values[0]
            )
            await self._refresh(interaction)
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    async def _on_onboarding(self, interaction: discord.Interaction) -> None:
        try:
            await ensure_level(interaction, PermissionLevel.STAFF)
            await self._bot.player_service.set_onboarding(
                self._guild_id, self._user_id, self._onboarding_next
            )
            await self._refresh(interaction)
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    async def _on_back(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.edit_message(
                content="⚙️ **Member management** — pick a member:",
                embed=None,
                view=MemberPickView(self._bot),
            )
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)
