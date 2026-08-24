"""Mission commands: /mission list · view · brief · validate · search · sync.

All commands are thin wrappers around MissionService. Reads come from the
local index (fast, works even when GitHub is down); briefings and validation
fetch live content from GitHub.
"""

from __future__ import annotations

import io
import logging
from datetime import timezone
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from app.bot.permissions import PermissionLevel, require
from app.database.models.mission import MissionIndexEntry
from app.errors import AppError, MissionNotFoundError, MissionsNotConfiguredError
from app.missions import MissionStatus, Objective
from app.services.missions import MissionService, SyncResult

if TYPE_CHECKING:
    from app.bot.bot import UnitBot

log = logging.getLogger(__name__)

_GREEN = discord.Colour.from_str("#43b581")
_RED = discord.Colour.from_str("#f04747")
_ORANGE = discord.Colour.from_str("#faa61a")
_BLURPLE = discord.Colour.blurple()

_STATUS_EMOJI = {
    "draft": "📝",
    "development": "🛠️",
    "review": "🔍",
    "ready": "🟢",
    "archived": "📦",
}

_OBJECTIVE_EMOJI = {"primary": "🎯", "secondary": "🔸", "optional": "🔹"}

_MAX_LIST_ENTRIES = 20
_EMBED_TEXT_LIMIT = 4000  # keep headroom below Discord's 4096 description cap


def _timestamp(entry_or_dt) -> str:
    """Discord relative-time markup for a (possibly naive-UTC) datetime."""
    moment = entry_or_dt
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return f"<t:{int(moment.timestamp())}:R>"


def _mission_line(entry: MissionIndexEntry) -> str:
    invalid_flag = "" if entry.is_valid else " ⚠️ *(fails validation)*"
    emoji = _STATUS_EMOJI.get(entry.status, "•")
    return (
        f"**{entry.mission_id}** — {entry.name}{invalid_flag}\n"
        f"{emoji} {entry.status} · {entry.map_name} · {entry.mission_type} · "
        f"{entry.difficulty} · {entry.minimum_players}–{entry.maximum_players} players · "
        f"by {entry.mission_maker}"
    )


def _brief_payload(mission_id: str, content: str) -> dict:
    """Kwargs for sending a briefing: single embed, or preview + file attachment."""
    if len(content) <= _EMBED_TEXT_LIMIT:
        embed = discord.Embed(
            title=f"{mission_id} — Briefing", description=content, colour=_BLURPLE
        )
        return {"embed": embed}
    preview = content[:1000].rsplit("\n", 1)[0]
    embed = discord.Embed(
        title=f"{mission_id} — Briefing",
        description=f"{preview}\n\n… *briefing is too long for Discord — full text attached.*",
        colour=_BLURPLE,
    )
    file = discord.File(
        io.BytesIO(content.encode("utf-8")), filename=f"{mission_id}-brief.md"
    )
    return {"embed": embed, "file": file}


def _objectives_embed(mission_id: str, objectives: list[Objective]) -> discord.Embed:
    lines = []
    for objective in objectives:
        emoji = _OBJECTIVE_EMOJI.get(objective.type.value, "•")
        required = "required" if objective.required else "not required"
        lines.append(
            f"{emoji} **{objective.id} — {objective.name}** ({objective.type.value}, {required})\n"
            f"{objective.description}"
        )
    description = "\n\n".join(lines)
    if len(description) > _EMBED_TEXT_LIMIT:
        description = description[:_EMBED_TEXT_LIMIT] + "\n…"
    return discord.Embed(
        title=f"{mission_id} — Objectives", description=description, colour=_BLURPLE
    )


class MissionDetailView(discord.ui.View):
    """Buttons under /mission view. Non-persistent: they expire after 10
    minutes or a bot restart — re-run the command to get fresh buttons."""

    def __init__(self, service: MissionService, mission_id: str) -> None:
        super().__init__(timeout=600)
        self._service = service
        self._mission_id = mission_id

    async def _respond(self, interaction: discord.Interaction, **kwargs) -> None:
        await interaction.followup.send(ephemeral=True, **kwargs)

    @discord.ui.button(label="View Brief", emoji="📄", style=discord.ButtonStyle.secondary)
    async def view_brief(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            content = await self._service.get_brief(self._mission_id)
        except AppError as exc:
            await self._respond(interaction, content=f"⚠️ {exc.user_message}")
            return
        await self._respond(interaction, **_brief_payload(self._mission_id, content))

    @discord.ui.button(label="View Objectives", emoji="🎯", style=discord.ButtonStyle.secondary)
    async def view_objectives(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            objectives = await self._service.get_objectives(self._mission_id)
        except AppError as exc:
            await self._respond(interaction, content=f"⚠️ {exc.user_message}")
            return
        await self._respond(
            interaction, embed=_objectives_embed(self._mission_id, objectives)
        )


class MissionsCog(commands.Cog):
    def __init__(self, bot: "UnitBot") -> None:
        self.bot = bot

    mission = app_commands.Group(
        name="mission",
        description="Unit mission repository",
        guild_only=True,
    )

    def _service(self) -> MissionService:
        service = self.bot.mission_service
        if service is None:
            raise MissionsNotConfiguredError()
        return service

    async def _mission_id_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        try:
            service = self._service()
            entries = await (service.search(current) if current.strip() else service.list_missions())
        except Exception:  # autocomplete must never raise
            return []
        return [
            app_commands.Choice(
                name=f"{entry.mission_id} — {entry.name}"[:100], value=entry.mission_id
            )
            for entry in entries[:25]
        ]

    async def _send_mission_listing(
        self,
        interaction: discord.Interaction,
        title: str,
        entries: list[MissionIndexEntry],
        empty_message: str,
    ) -> None:
        if not entries:
            await interaction.followup.send(f"📭 {empty_message}")
            return
        shown = entries[:_MAX_LIST_ENTRIES]
        embed = discord.Embed(
            title=title,
            description="\n\n".join(_mission_line(entry) for entry in shown),
            colour=_BLURPLE,
        )
        if len(entries) > len(shown):
            embed.description += (
                f"\n\n… and {len(entries) - len(shown)} more — narrow it down with filters."
            )
        last_synced = await self._service().last_synced_at()
        if last_synced is not None:
            embed.add_field(
                name="Index last synced",
                value=f"{_timestamp(last_synced)} — `/mission sync` refreshes it",
                inline=False,
            )
        await interaction.followup.send(embed=embed)

    # --- commands ------------------------------------------------------------

    @mission.command(name="list", description="List missions from the unit repository")
    @app_commands.describe(
        status="Only show missions with this status",
        map_name="Only show missions on this map",
        mission_type="Only show missions of this type (e.g. Direct Action)",
    )
    @app_commands.rename(map_name="map", mission_type="type")
    @require(PermissionLevel.MEMBER)
    async def mission_list(
        self,
        interaction: discord.Interaction,
        status: MissionStatus | None = None,
        map_name: str | None = None,
        mission_type: str | None = None,
    ) -> None:
        await interaction.response.defer(thinking=True)
        entries = await self._service().list_missions(
            status=status.value if status else None,
            map_name=map_name,
            mission_type=mission_type,
        )
        filters = [
            f"status: {status.value}" if status else None,
            f"map: {map_name}" if map_name else None,
            f"type: {mission_type}" if mission_type else None,
        ]
        active_filters = ", ".join(f for f in filters if f)
        title = f"Missions ({len(entries)})" + (f" — {active_filters}" if active_filters else "")
        await self._send_mission_listing(
            interaction,
            title,
            entries,
            "No missions found."
            + (" Try different filters, or" if active_filters else " The index is empty —")
            + " ask staff to run `/mission sync`.",
        )

    @mission.command(name="view", description="Show a mission's full details")
    @app_commands.describe(mission_id="Mission ID, e.g. OP-001")
    @app_commands.autocomplete(mission_id=_mission_id_autocomplete)
    @require(PermissionLevel.MEMBER)
    async def mission_view(self, interaction: discord.Interaction, mission_id: str) -> None:
        await interaction.response.defer(thinking=True)
        service = self._service()
        entry = await service.get_mission(mission_id)
        if entry is None:
            raise MissionNotFoundError(mission_id)

        emoji = _STATUS_EMOJI.get(entry.status, "•")
        embed = discord.Embed(
            title=f"{entry.mission_id} — {entry.name}",
            description=entry.description,
            colour=_GREEN if entry.is_valid else _ORANGE,
        )
        embed.add_field(name="Status", value=f"{emoji} {entry.status}")
        embed.add_field(name="Map", value=entry.map_name)
        embed.add_field(name="Type", value=entry.mission_type)
        embed.add_field(name="Difficulty", value=entry.difficulty)
        embed.add_field(
            name="Players", value=f"{entry.minimum_players}–{entry.maximum_players}"
        )
        embed.add_field(name="Duration", value=f"~{entry.estimated_duration_minutes} min")
        embed.add_field(name="Version", value=entry.version)
        embed.add_field(name="Mission maker", value=entry.mission_maker)
        embed.add_field(name="Factions", value=", ".join(entry.factions) or "—")
        if entry.required_mods:
            mods = "\n".join(f"• {mod}" for mod in entry.required_mods)
            embed.add_field(name="Required mods", value=mods[:1024], inline=False)
        if entry.tags:
            embed.add_field(name="Tags", value=", ".join(entry.tags), inline=False)
        if not entry.is_valid:
            problems = "\n".join(f"✗ {error}" for error in entry.validation_errors[:3])
            if len(entry.validation_errors) > 3:
                problems += f"\n… {len(entry.validation_errors) - 3} more"
            embed.add_field(name="⚠️ Fails validation", value=problems[:1024], inline=False)
        embed.set_footer(text=f"As of last sync {entry.directory}")

        await interaction.followup.send(
            embed=embed, view=MissionDetailView(service, entry.mission_id)
        )

    @mission.command(name="brief", description="Show a mission's briefing")
    @app_commands.describe(mission_id="Mission ID, e.g. OP-001")
    @app_commands.autocomplete(mission_id=_mission_id_autocomplete)
    @require(PermissionLevel.MEMBER)
    async def mission_brief(self, interaction: discord.Interaction, mission_id: str) -> None:
        await interaction.response.defer(thinking=True)
        content = await self._service().get_brief(mission_id)
        await interaction.followup.send(**_brief_payload(mission_id.upper(), content))

    @mission.command(
        name="validate", description="Validate a mission against the repository's current files"
    )
    @app_commands.describe(mission_id="Mission ID, e.g. OP-001")
    @app_commands.autocomplete(mission_id=_mission_id_autocomplete)
    @require(PermissionLevel.MEMBER)
    async def mission_validate(self, interaction: discord.Interaction, mission_id: str) -> None:
        await interaction.response.defer(thinking=True)
        report = await self._service().validate_mission(mission_id)

        lines = [f"✓ {name}" for name in report.passed]
        lines += [f"✗ {error}" for error in report.errors]
        lines += [f"⚠ {warning}" for warning in report.warnings]
        body = "\n".join(lines)[:_EMBED_TEXT_LIMIT]

        if report.metadata is not None:
            header = f"**{report.metadata.id} — {report.metadata.name}**\nVersion {report.metadata.version}"
        else:
            header = f"**{report.directory}**"

        embed = discord.Embed(
            title="🟢 Mission valid" if report.is_valid else "🔴 Mission invalid",
            description=f"{header}\n\n{body}",
            colour=_GREEN if report.is_valid else _RED,
        )
        await interaction.followup.send(embed=embed)

    @mission.command(name="search", description="Search missions by name, map, tags, maker, …")
    @app_commands.describe(query="Text to search for")
    @require(PermissionLevel.MEMBER)
    async def mission_search(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer(thinking=True)
        entries = await self._service().search(query)
        await self._send_mission_listing(
            interaction,
            f"Search results for “{query}” ({len(entries)})",
            entries,
            f"No missions match “{query}”.",
        )

    @mission.command(
        name="sync", description="Staff: refresh the mission index from GitHub"
    )
    @require(PermissionLevel.STAFF)
    async def mission_sync(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        service = self._service()
        result: SyncResult = await service.sync()

        healthy = not result.failures and result.invalid == 0
        embed = discord.Embed(
            title="Mission index synchronized",
            colour=_GREEN if healthy else _ORANGE,
            description=f"Source: {service.repository_url}",
        )
        embed.add_field(name="Directories found", value=str(result.found))
        embed.add_field(
            name="Indexed", value=f"{result.indexed} ({result.valid} valid, {result.invalid} invalid)"
        )
        embed.add_field(name="Stale entries removed", value=str(result.removed))
        if result.failures:
            failure_lines = "\n".join(
                f"✗ `{failure.directory}` — {failure.errors[0]}" for failure in result.failures[:5]
            )
            if len(result.failures) > 5:
                failure_lines += f"\n… {len(result.failures) - 5} more"
            embed.add_field(
                name="Could not be indexed", value=failure_lines[:1024], inline=False
            )
        await interaction.followup.send(embed=embed)


async def setup(bot: "UnitBot") -> None:
    await bot.add_cog(MissionsCog(bot))
