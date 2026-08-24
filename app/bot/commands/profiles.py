"""Member identity commands: /profile, /stats, /members (staff)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from app.bot import embeds
from app.bot.permissions import PermissionLevel, member_level, require
from app.bot.views.members import MemberPickView, build_member_panel
from app.bot.views.profile_setup import ProfileSetupView

if TYPE_CHECKING:
    from app.bot.bot import UnitBot


class ProfileEditButton(discord.ui.View):
    def __init__(self, bot: "UnitBot", member: discord.Member) -> None:
        super().__init__(timeout=600)
        self._bot = bot
        self._member = member

    @discord.ui.button(label="Set up / edit profile", emoji="⚙️",
                       style=discord.ButtonStyle.secondary)
    async def edit(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.user.id != self._member.id:
            await interaction.response.send_message(
                "This button belongs to someone else's profile — run `/profile` yourself.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "⚙️ **Profile setup** — everything is optional, changes save instantly:",
            view=ProfileSetupView(self._bot, self._member),
            ephemeral=True,
        )


class ProfilesCog(commands.Cog):
    def __init__(self, bot: "UnitBot") -> None:
        self.bot = bot

    @app_commands.command(description="Your unit profile — or another member's")
    @app_commands.describe(member="Leave empty for your own profile")
    @app_commands.guild_only()
    @require(PermissionLevel.MEMBER)
    async def profile(
        self, interaction: discord.Interaction, member: discord.Member | None = None
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        assert interaction.guild is not None and isinstance(interaction.user, discord.Member)
        target = member or interaction.user
        if target.bot:
            await interaction.followup.send("🤖 Bots don't have unit profiles.", ephemeral=True)
            return

        own = target.id == interaction.user.id
        viewer_level = await member_level(self.bot, interaction.user)
        staff_view = viewer_level >= PermissionLevel.STAFF and not own

        player = await self.bot.player_service.get_or_create(
            interaction.guild.id, target.id, target.display_name,
            joined_at=target.joined_at,
        )
        qualifications = await self.bot.player_service.qualifications(player.id)

        # Visibility: participation stats are self + staff only ("minimal" policy).
        stats = history = None
        if own or staff_view:
            stats = await self.bot.attendance_service.player_stats(
                interaction.guild.id, target.id
            )
            history = await self.bot.attendance_service.recent_history(
                interaction.guild.id, target.id
            )
        embed = embeds.profile_embed(
            player, qualifications, stats=stats, history=history,
            viewer="own" if own else ("staff" if staff_view else "member"),
        )
        view = ProfileEditButton(self.bot, interaction.user) if own else None
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @app_commands.command(description="Unit participation statistics")
    @app_commands.guild_only()
    @require(PermissionLevel.MEMBER)
    async def stats(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        assert interaction.guild is not None
        unit_stats = await self.bot.attendance_service.unit_stats(interaction.guild.id)
        configuration = await self.bot.guild_service.get_configuration(interaction.guild.id)
        unit_name = configuration.unit_name if configuration else None
        await interaction.followup.send(embed=embeds.unit_stats_embed(unit_stats, unit_name))

    @app_commands.command(name="members", description="Staff: view and manage unit members")
    @app_commands.describe(search="Filter by display name (optional)")
    @app_commands.guild_only()
    @require(PermissionLevel.STAFF)
    async def members(
        self, interaction: discord.Interaction, search: str | None = None
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        assert interaction.guild is not None
        if search:
            matches = await self.bot.player_service.search_members(
                interaction.guild.id, search, limit=1
            )
            if matches:
                player = matches[0]
                embed, view = await build_member_panel(
                    self.bot, interaction.guild.id,
                    player.discord_user_id, player.display_name,
                )
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)
                return
            await interaction.followup.send(
                f"📭 No member profile matches “{search}” — pick from the list instead:",
                view=MemberPickView(self.bot),
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            "⚙️ **Member management** — pick a member:",
            view=MemberPickView(self.bot),
            ephemeral=True,
        )


async def setup(bot: "UnitBot") -> None:
    await bot.add_cog(ProfilesCog(bot))
