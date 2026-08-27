"""Staff/admin commands: /unit setup · sync · diagnostics."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from app import __version__
from app.bot import embeds
from app.bot.permissions import (
    PermissionLevel,
    ensure_developer,
    ensure_level,
    require,
)
from app.bot.views.components import respond_error
from app.bot.views.publish import refresh_guild_publications
from app.bot.views.setup import SetupHubView, build_setup_embed

if TYPE_CHECKING:
    from app.bot.bot import UnitBot


class ForgetMemoryView(discord.ui.View):
    """Select-to-delete for the assistant's server memory."""

    def __init__(self, bot: "UnitBot", memories) -> None:
        super().__init__(timeout=600)
        self._bot = bot
        select = discord.ui.Select(
            placeholder="🗑️ Forget a memory…",
            options=[
                discord.SelectOption(
                    label=f"#{memory.id} {memory.content[:80]}"[:100], value=str(memory.id)
                )
                for memory in memories[:25]
            ],
        )
        select.callback = self._on_forget  # type: ignore[method-assign]
        self._select = select
        self.add_item(select)

    async def _on_forget(self, interaction: discord.Interaction) -> None:
        try:
            await ensure_level(interaction, PermissionLevel.STAFF)
            memory_id = int(self._select.values[0])
            removed = await self._bot.memory_service.forget(
                interaction.guild.id, memory_id  # type: ignore[union-attr]
            )
            await interaction.response.send_message(
                f"🗑️ Memory `#{memory_id}` {'forgotten' if removed else 'was already gone'}. "
                "Run `/unit memories` again to see the updated list.",
                ephemeral=True,
            )
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)


class UnitCog(commands.Cog):
    def __init__(self, bot: "UnitBot") -> None:
        self.bot = bot

    unit = app_commands.Group(
        name="unit",
        description="Unit configuration and administration",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @unit.command(name="setup", description="Configure channels, roles, timezone and reminders")
    @require(PermissionLevel.ADMIN)
    async def unit_setup(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        assert interaction.guild is not None
        configuration = await self.bot.guild_service.register_guild(
            interaction.guild.id, interaction.guild.name
        )
        await interaction.followup.send(
            embed=build_setup_embed(interaction.guild, configuration),
            view=SetupHubView(self.bot, interaction.guild),
            ephemeral=True,
        )

    @unit.command(
        name="sync",
        description="Re-index unit knowledge/lore and refresh missions from GitHub",
    )
    @require(PermissionLevel.STAFF)
    async def unit_sync(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        assert interaction.guild is not None

        # Local unit knowledge + lore always sync; missions need GitHub.
        knowledge = await self.bot.knowledge_service.sync()
        result = None
        updated = stale = 0
        if self.bot.mission_service is not None:
            result = await self.bot.mission_service.sync()
            updated, stale = await refresh_guild_publications(self.bot, interaction.guild.id)

        healthy = not knowledge.failures and (
            result is None or (not result.failures and result.invalid == 0)
        )
        embed = discord.Embed(
            title="Unit sync complete",
            colour=embeds.GREEN if healthy else embeds.ORANGE,
        )
        knowledge_value = (
            f"{knowledge.indexed} docs indexed, {knowledge.removed} removed "
            f"(from `unit/knowledge` + `unit/lore`)"
        )
        if knowledge.failures:
            knowledge_value += "\n" + "\n".join(
                f"✗ `{path}` — {error}" for path, error in knowledge.failures[:4]
            )
        embed.add_field(name="Knowledge base", value=knowledge_value[:1024], inline=False)
        if result is not None:
            embed.add_field(
                name="Missions",
                value=(
                    f"{result.indexed} indexed ({result.valid} valid, {result.invalid} "
                    f"invalid), {result.removed} removed — "
                    f"{self.bot.mission_service.repository_url}"
                ),
                inline=False,
            )
            embed.add_field(name="Published posts refreshed", value=f"{updated} ({stale} stale)")
            if result.failures:
                failure_lines = "\n".join(
                    f"✗ `{failure.directory}` — {failure.errors[0]}"
                    for failure in result.failures[:5]
                )
                embed.add_field(
                    name="Could not be indexed", value=failure_lines[:1024], inline=False
                )
        else:
            embed.add_field(
                name="Missions",
                value="⚠️ Repository not configured (GITHUB_MISSIONS_* in .env)",
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @unit.command(name="memories", description="Review and prune the assistant's server memory")
    @require(PermissionLevel.STAFF)
    async def unit_memories(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        assert interaction.guild is not None
        memories = await self.bot.memory_service.list_recent(interaction.guild.id)
        total = await self.bot.memory_service.count(interaction.guild.id)
        if not memories:
            await interaction.followup.send(
                "🧠 Server memory is empty — the assistant saves facts as it "
                "learns them from conversations.",
                ephemeral=True,
            )
            return
        lines = [
            f"`#{memory.id}` {memory.content[:150]} — <t:{int(memory.created_at.timestamp())}:R>"
            if memory.created_at.tzinfo
            else f"`#{memory.id}` {memory.content[:150]}"
            for memory in memories
        ]
        embed = discord.Embed(
            title=f"🧠 Server memory ({total} total, newest {len(memories)})",
            description="\n".join(lines)[:4000],
            colour=embeds.BLURPLE,
        )
        await interaction.followup.send(
            embed=embed, view=ForgetMemoryView(self.bot, memories), ephemeral=True
        )

    @unit.command(
        name="export",
        description="Export all unit data to one Excel workbook (attached here)",
    )
    @require(PermissionLevel.STAFF)
    async def unit_export(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        assert interaction.guild is not None
        context = self.bot.server_data.ensure(interaction.guild.id, interaction.guild.name)
        path, counts = await self.bot.data_export.export_workbook(
            interaction.guild.id, context.exports_dir
        )
        await self.bot.data_export.write_memory_snapshot(
            interaction.guild.id, context.memory_dir
        )

        embed = discord.Embed(
            title="📦 Unit data exported",
            colour=embeds.GREEN,
            description=(
                f"One Excel workbook — `{path.name}` — with a sheet per dataset, "
                "attached below and saved in the server's `exports/` folder "
                "(only the newest 10 exports are kept; `exports/latest/` holds "
                "the same data as always-current CSVs)."
            ),
        )
        for name, count in counts.items():
            embed.add_field(name=name.capitalize(), value=f"{count} rows")
        files = []
        if path.stat().st_size < 7_500_000:
            files.append(discord.File(str(path), filename=path.name))
        await interaction.followup.send(embed=embed, files=files, ephemeral=True)

    @unit.command(
        name="usage",
        description="Developers: AI credit usage — requests, tokens, estimated cost",
    )
    @require(PermissionLevel.MEMBER)
    async def unit_usage(self, interaction: discord.Interaction) -> None:
        # Developer-only: spend data is infrastructure trust, not staff trust.
        await ensure_developer(interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        summary = await self.bot.ai_usage.summary(days=30)

        if not summary.days:
            await interaction.followup.send(
                "📊 No AI usage recorded yet (tracking started with v0.13). "
                "Ask the assistant something and check again.",
                ephemeral=True,
            )
            return

        cost = (
            f"~${summary.estimated_cost_usd:.4f}"
            if summary.estimated_cost_usd is not None
            else "n/a (no public price for this model)"
        )
        embed = discord.Embed(
            title="📊 AI usage — last 30 days",
            colour=embeds.BLURPLE,
            description=(
                f"**{summary.total_requests}** requests · "
                f"**{summary.total_input_tokens:,}** tokens in · "
                f"**{summary.total_output_tokens:,}** tokens out\n"
                f"**Estimated cost:** {cost}\n"
                "-# Estimates use public prices; the provider's invoice is authoritative."
            ),
        )
        from app.services.ai_usage import estimate_cost_usd

        lines = []
        for row in summary.days[:14]:
            day_cost = estimate_cost_usd(row.model, row.input_tokens, row.output_tokens)
            cost_text = f" · ~${day_cost:.4f}" if day_cost is not None else ""
            lines.append(
                f"`{row.day}` {row.provider}/{row.model} — {row.requests} req · "
                f"{row.input_tokens:,} in · {row.output_tokens:,} out{cost_text}"
            )
        embed.add_field(name="By day", value="\n".join(lines)[:1024], inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @unit.command(name="diagnostics", description="Bot, database and repository health")
    @require(PermissionLevel.STAFF)
    async def unit_diagnostics(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        assert interaction.guild is not None
        report = await self.bot.status_service.check()
        configuration = await self.bot.guild_service.get_configuration(interaction.guild.id)

        embed = discord.Embed(
            title="🩺 Unit diagnostics",
            colour=embeds.GREEN if report.database_connected else embeds.ORANGE,
        )
        embed.add_field(name="Bot", value=f"🟢 v{report.version} ({report.environment})")
        embed.add_field(
            name="Database",
            value="🟢 Connected" if report.database_connected else "🔴 Unreachable",
        )
        embed.add_field(
            name="Mission repository",
            value=(
                f"🟢 {self.bot.mission_service.repository_url}"
                if self.bot.mission_service
                else "⚠️ Not configured (GITHUB_MISSIONS_* in .env)"
            ),
            inline=False,
        )
        if self.bot.assistant_service is not None and self.bot.ai_client is not None:
            knowledge_count = await self.bot.knowledge_service.document_count()
            embed.add_field(
                name="Unit assistant",
                value=(
                    f"🟢 {self.bot.settings.ai_provider} · {self.bot.ai_client.model} · "
                    f"{knowledge_count} knowledge docs indexed"
                ),
                inline=False,
            )
        else:
            embed.add_field(
                name="Unit assistant",
                value="⚠️ Disabled — set OPENAI_API_KEY or GEMINI_API_KEY (+ AI_PROVIDER)",
                inline=False,
            )
        unit_status = self.bot.unit_config.status()
        if not unit_status.initialized:
            unit_value = "⚠️ Not initialized — restart the bot to copy templates into `unit/`"
        else:
            unit_value = (
                f"🟢 v{unit_status.schema_version} · {unit_status.lore_documents} lore + "
                f"{unit_status.knowledge_documents} knowledge docs · personality "
                + ("customized" if unit_status.personality_customized else "template (edit `unit/personality/personality.md`)")
            )
        embed.add_field(name="Unit configuration", value=unit_value, inline=False)
        if configuration is None:
            embed.add_field(
                name="Server configuration",
                value="⚠️ Not registered — run `/unit setup`",
                inline=False,
            )
        else:
            unset = [
                label
                for key, label in (
                    ("operations_channel_id", "operations channel"),
                    ("missions_channel_id", "missions channel"),
                    ("timezone", "timezone"),
                )
                if not getattr(configuration, key)
            ]
            embed.add_field(
                name="Server configuration",
                value="🟢 Ready for operations" if not unset
                else "⚠️ Missing: " + ", ".join(unset) + " → `/unit setup`",
                inline=False,
            )
            upcoming = await self.bot.operation_service.list_upcoming(interaction.guild.id)
            embed.add_field(name="Upcoming operations", value=str(len(upcoming)))
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: "UnitBot") -> None:
    await bot.add_cog(UnitCog(bot))
