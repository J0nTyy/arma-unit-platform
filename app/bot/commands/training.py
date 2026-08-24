"""Training & certification commands.

Trainers (the configured Trainer role, or staff) grant certifications after
training a member. Granting a cert also assigns the matching Discord role
(created automatically the first time); revoking removes it. Eligibility
rules live in CERT_REQUIREMENTS (app/database/models/player.py) — edit them
there, nothing else needs to change.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from app.bot import embeds
from app.bot.permissions import PermissionLevel, ensure_trainer, is_trainer, require
from app.database.models.player import CERT_REQUIREMENTS, QUALIFICATIONS

if TYPE_CHECKING:
    from app.bot.bot import UnitBot

log = logging.getLogger(__name__)

_CERT_CHOICES = [
    app_commands.Choice(name=label, value=slug) for slug, label in QUALIFICATIONS.items()
]


def _role_name(cert: str) -> str:
    """Discord role name for a cert — the label without its emoji."""
    return QUALIFICATIONS[cert].split(" ", 1)[1]


async def _sync_cert_role(
    guild: discord.Guild, member: discord.Member, cert: str, *, grant: bool
) -> str | None:
    """Assign/remove the cert's Discord role. Returns a warning or None."""
    name = _role_name(cert)
    role = discord.utils.get(guild.roles, name=name)
    try:
        if role is None and grant:
            role = await guild.create_role(
                name=name, mentionable=False, reason="Training certification role"
            )
        if role is None:
            return None
        if grant:
            await member.add_roles(role, reason="Certification granted")
        elif role in member.roles:
            await member.remove_roles(role, reason="Certification revoked")
        return None
    except discord.Forbidden:
        return (
            f"⚠️ Couldn't {'assign' if grant else 'remove'} the **{name}** Discord role — "
            "give me Manage Roles permission (and drag my role above the cert roles)."
        )


class TrainingCog(commands.Cog):
    def __init__(self, bot: "UnitBot") -> None:
        self.bot = bot

    training = app_commands.Group(
        name="training", description="Training and certifications", guild_only=True
    )

    @training.command(name="info", description="All certifications and their requirements")
    @require(PermissionLevel.MEMBER)
    async def training_info(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        assert interaction.guild is not None
        configuration = await self.bot.guild_service.get_configuration(interaction.guild.id)
        trainer_role = (
            f"<@&{configuration.trainer_role_id}>"
            if configuration and configuration.trainer_role_id
            else "*not set — staff can set it in `/unit setup`*"
        )
        lines = []
        for cert, label in QUALIFICATIONS.items():
            requirements = CERT_REQUIREMENTS.get(cert, {})
            parts = []
            if requirements.get("min_attended"):
                parts.append(f"{requirements['min_attended']} ops attended")
            for prerequisite in requirements.get("requires", ()):
                parts.append(f"{QUALIFICATIONS.get(prerequisite, prerequisite)} first")
            lines.append(f"{label} — {', '.join(parts) if parts else 'no requirements'}")
        embed = discord.Embed(
            title="🎓 Certifications",
            description=(
                "Meet the requirements, then ask a trainer for a training session. "
                "After training, the trainer grants the cert — you get the Discord "
                "role automatically.\n\n" + "\n".join(lines)
            ),
            colour=embeds.BLURPLE,
        )
        embed.add_field(name="Trainers", value=trainer_role)
        embed.set_footer(text="Check your own eligibility with /training certs")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @training.command(name="certs", description="Your certifications and what you can train for")
    @app_commands.describe(member="(Trainers/staff) check another member")
    @require(PermissionLevel.MEMBER)
    async def training_certs(
        self, interaction: discord.Interaction, member: discord.Member | None = None
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        assert interaction.guild is not None and isinstance(interaction.user, discord.Member)
        target = member or interaction.user
        if target.id != interaction.user.id and not await is_trainer(
            self.bot, interaction.user
        ):
            await interaction.followup.send(
                "🔒 Checking someone else's eligibility needs the Trainer role or staff.",
                ephemeral=True,
            )
            return
        statuses = await self.bot.player_service.cert_eligibility(
            interaction.guild.id, target.id
        )
        held = [s.label for s in statuses if s.held]
        ready = [s.label for s in statuses if not s.held and s.eligible]
        locked = [
            f"{s.label} — {', '.join(s.missing)}"
            for s in statuses
            if not s.held and not s.eligible
        ]
        embed = discord.Embed(
            title=f"🎓 {target.display_name} — Certifications", colour=embeds.BLURPLE
        )
        embed.add_field(name="🏅 Held", value="\n".join(held) or "*None yet*", inline=False)
        embed.add_field(
            name="✅ Eligible to train",
            value="\n".join(ready) or "*Nothing new right now*",
            inline=False,
        )
        if locked:
            embed.add_field(name="🔒 Not yet", value="\n".join(locked)[:1024], inline=False)
        embed.set_footer(text="Requirements are set by staff · /training info")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @training.command(name="grant", description="Trainer: certify a member after training")
    @app_commands.describe(member="Who completed the training", cert="Which certification")
    @app_commands.choices(cert=_CERT_CHOICES)
    @require(PermissionLevel.MEMBER)
    async def training_grant(
        self, interaction: discord.Interaction, member: discord.Member, cert: str
    ) -> None:
        await ensure_trainer(interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        assert interaction.guild is not None
        if member.bot:
            await interaction.followup.send("🤖 Bots train themselves.", ephemeral=True)
            return
        await self.bot.player_service.get_or_create(
            interaction.guild.id, member.id, member.display_name
        )
        await self.bot.player_service.grant_qualification(
            interaction.guild.id, member.id, cert, granted_by=interaction.user.id
        )
        warning = await _sync_cert_role(interaction.guild, member, cert, grant=True)
        note = f"\n{warning}" if warning else ""
        await interaction.followup.send(
            f"🎓 **{QUALIFICATIONS[cert]}** granted to {member.mention}.{note}",
            ephemeral=True,
        )
        # Congratulate publicly — small things build unit culture.
        configuration = await self.bot.guild_service.get_configuration(interaction.guild.id)
        channel_id = configuration.general_channel_id if configuration else None
        channel = interaction.guild.get_channel(channel_id) if channel_id else None
        if channel is not None:
            try:
                await channel.send(
                    f"🎓 {member.mention} just earned **{QUALIFICATIONS[cert]}** — "
                    f"trained by {interaction.user.display_name}. o7"
                )
            except discord.HTTPException:
                pass

    @training.command(name="revoke", description="Trainer: revoke a member's certification")
    @app_commands.describe(member="Whose certification", cert="Which certification")
    @app_commands.choices(cert=_CERT_CHOICES)
    @require(PermissionLevel.MEMBER)
    async def training_revoke(
        self, interaction: discord.Interaction, member: discord.Member, cert: str
    ) -> None:
        await ensure_trainer(interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        assert interaction.guild is not None
        await self.bot.player_service.revoke_qualification(
            interaction.guild.id, member.id, cert
        )
        warning = await _sync_cert_role(interaction.guild, member, cert, grant=False)
        note = f"\n{warning}" if warning else ""
        await interaction.followup.send(
            f"❌ **{QUALIFICATIONS[cert]}** revoked from {member.mention}.{note}",
            ephemeral=True,
        )


async def setup(bot: "UnitBot") -> None:
    await bot.add_cog(TrainingCog(bot))
