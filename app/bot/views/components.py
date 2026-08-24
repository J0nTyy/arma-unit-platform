"""Persistent UI components (survive bot restarts).

These are discord.py DynamicItems: their state lives entirely in the button's
custom_id, so a restarted bot can handle clicks on messages posted weeks ago.
Register the classes once in UnitBot.setup_hook via add_dynamic_items().

Permission note: every callback re-checks authorization server-side —
Discord UI visibility is never trusted (see app.bot.permissions).
"""

from __future__ import annotations

import io
import logging
import re
from typing import TYPE_CHECKING

import discord

from app.bot import embeds
from app.bot.permissions import PermissionDeniedError, PermissionLevel, ensure_level
from app.database.models.operation import AttendanceStatus, Operation, OperationStatus
from app.errors import AppError, MissionsNotConfiguredError
from app.missions import Objective

if TYPE_CHECKING:
    from app.bot.bot import UnitBot

log = logging.getLogger(__name__)

_EMBED_TEXT_LIMIT = 4000


def _embed_size(embed: discord.Embed) -> int:
    total = len(embed.title or "") + len(embed.description or "")
    for field in embed.fields:
        total += len(field.name or "") + len(field.value or "")
    return total


def group_embeds(items: list[discord.Embed], budget: int = 5600) -> list[list[discord.Embed]]:
    """Group embeds into messages under Discord's per-message size budget."""
    groups: list[list[discord.Embed]] = []
    current: list[discord.Embed] = []
    size = 0
    for embed in items:
        embed_size = _embed_size(embed)
        if current and (size + embed_size > budget or len(current) >= 8):
            groups.append(current)
            current, size = [], 0
        current.append(embed)
        size += embed_size
    if current:
        groups.append(current)
    return groups


def brief_message_kwargs(title: str, content: str) -> dict:
    """Pretty briefing for a single (ephemeral) message; falls back to a file
    attachment when the briefing exceeds one message's budget."""
    rendered = embeds.brief_embeds(title, content)
    groups = group_embeds(rendered)
    if len(groups) == 1:
        return {"embeds": groups[0]}
    preview = rendered[0]
    preview.set_footer(text="Briefing is very long — full text attached as a file.")
    file = discord.File(io.BytesIO(content.encode("utf-8")), filename=f"{title}-brief.md")
    return {"embeds": [preview], "file": file}


def objectives_message_embed(mission_id: str, objectives: list[Objective]) -> discord.Embed:
    icon = {"primary": "🎯", "secondary": "🔸", "optional": "◽"}
    lines = []
    for objective in objectives:
        required = "required" if objective.required else "optional"
        lines.append(
            f"{icon.get(objective.type.value, '•')} **{objective.id} — {objective.name}** "
            f"({objective.type.value}, {required})\n{objective.description}"
        )
    description = "\n\n".join(lines)[:_EMBED_TEXT_LIMIT]
    return discord.Embed(
        title=f"🎯 {mission_id} — Objectives", description=description, colour=embeds.BLURPLE
    )


async def respond_error(interaction: discord.Interaction, error: Exception) -> None:
    """Uniform error responses for component callbacks."""
    if isinstance(error, PermissionDeniedError):
        content = f"🔒 This action requires **{error.required.name.replace('_', ' ').title()}** access."
    elif isinstance(error, AppError):
        content = f"⚠️ {error.user_message}"
    else:
        log.exception("Component interaction failed", exc_info=error)
        content = "❌ Something went wrong. The error has been logged."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=True)
        else:
            await interaction.response.send_message(content, ephemeral=True)
    except discord.HTTPException:
        log.warning("Could not deliver component error message")


def _bot(interaction: discord.Interaction) -> "UnitBot":
    return interaction.client  # type: ignore[return-value]


def _mission_service(interaction: discord.Interaction):
    service = _bot(interaction).mission_service
    if service is None:
        raise MissionsNotConfiguredError()
    return service


async def refresh_operation_message(bot: "UnitBot", operation: Operation) -> None:
    """Rebuild the operation post after any state/attendance change."""
    if operation.channel_id is None or operation.message_id is None:
        return
    try:
        channel = bot.get_channel(operation.channel_id) or await bot.fetch_channel(
            operation.channel_id
        )
        message = channel.get_partial_message(operation.message_id)  # type: ignore[union-attr]
        roster = await bot.operation_service.roster(operation.id)
        mission = None
        if bot.mission_service is not None:
            mission = await bot.mission_service.get_mission(operation.mission_id)
        await message.edit(
            embed=embeds.operation_embed(operation, mission, roster),
            view=operation_post_view(operation),
        )
    except discord.NotFound:
        log.warning("Operation %d post is gone (deleted?)", operation.id)
    except (discord.HTTPException, AppError):
        log.exception("Could not refresh post for operation %d", operation.id)


_ATTENDANCE_LABELS = {
    "attending": ("🟢", "Attend", discord.ButtonStyle.success),
    "maybe": ("🟡", "Maybe", discord.ButtonStyle.secondary),
    "declined": ("🔴", "Can't Attend", discord.ButtonStyle.secondary),
}


class AttendanceButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"arma:op:(?P<op>\d+):att:(?P<st>attending|maybe|declined)",
):
    def __init__(self, operation_id: int, status: str) -> None:
        emoji, label, style = _ATTENDANCE_LABELS[status]
        super().__init__(
            discord.ui.Button(
                label=label,
                emoji=emoji,
                style=style,
                custom_id=f"arma:op:{operation_id}:att:{status}",
            )
        )
        self.operation_id = operation_id
        self.status = status

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str]):
        return cls(int(match["op"]), match["st"])

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            await ensure_level(interaction, PermissionLevel.MEMBER)
            await interaction.response.defer(ephemeral=True, thinking=True)
            bot = _bot(interaction)
            outcome = await bot.operation_service.set_attendance(
                self.operation_id,
                interaction.user.id,
                interaction.user.display_name,
                AttendanceStatus(self.status),
            )
            operation = outcome.operation
            if outcome.status == AttendanceStatus.WAITLIST.value:
                message = (
                    f"⚠️ **{operation.name}** is full.\n"
                    f"You have been added to the waitlist at position **#{outcome.waitlist_position}** — "
                    "you'll be moved in automatically when a slot opens."
                )
            elif outcome.status == AttendanceStatus.ATTENDING.value:
                message = f"🟢 You're attending **{operation.name}**."
            elif outcome.status == AttendanceStatus.MAYBE.value:
                message = f"🟡 Marked as **maybe** for **{operation.name}**."
            else:
                message = f"🔴 Your attendance has been updated — not attending **{operation.name}**."
            await interaction.followup.send(message, ephemeral=True)

            await refresh_operation_message(bot, operation)
            if outcome.promoted and operation.channel_id:
                channel = bot.get_channel(operation.channel_id)
                if channel is not None:
                    mentions = ", ".join(f"<@{r.user_id}>" for r in outcome.promoted)
                    await channel.send(
                        f"🟢 A slot has opened in **{operation.name}** — "
                        f"{mentions} moved from the waitlist into the operation.",
                        reference=discord.MessageReference(
                            message_id=operation.message_id,
                            channel_id=operation.channel_id,
                            fail_if_not_exists=False,
                        )
                        if operation.message_id
                        else None,
                    )
        except Exception as error:  # noqa: BLE001 — must answer the interaction
            await respond_error(interaction, error)


class RosterButton(
    discord.ui.DynamicItem[discord.ui.Button], template=r"arma:op:(?P<op>\d+):roster"
):
    def __init__(self, operation_id: int) -> None:
        super().__init__(
            discord.ui.Button(
                label="View Roster",
                emoji="👥",
                style=discord.ButtonStyle.secondary,
                custom_id=f"arma:op:{operation_id}:roster",
            )
        )
        self.operation_id = operation_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str]):
        return cls(int(match["op"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            await ensure_level(interaction, PermissionLevel.MEMBER)
            await interaction.response.defer(ephemeral=True, thinking=True)
            bot = _bot(interaction)
            operation = await bot.operation_service.get(self.operation_id)
            roster = await bot.operation_service.roster(self.operation_id)
            await interaction.followup.send(
                embed=embeds.roster_embed(operation, roster), ephemeral=True
            )
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)


class OperationBriefButton(
    discord.ui.DynamicItem[discord.ui.Button], template=r"arma:op:(?P<op>\d+):brief"
):
    def __init__(self, operation_id: int) -> None:
        super().__init__(
            discord.ui.Button(
                label="View Brief",
                emoji="📖",
                style=discord.ButtonStyle.secondary,
                custom_id=f"arma:op:{operation_id}:brief",
            )
        )
        self.operation_id = operation_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str]):
        return cls(int(match["op"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            await ensure_level(interaction, PermissionLevel.MEMBER)
            await interaction.response.defer(ephemeral=True, thinking=True)
            bot = _bot(interaction)
            operation = await bot.operation_service.get(self.operation_id)
            content = await _mission_service(interaction).get_brief(operation.mission_id)
            await interaction.followup.send(
                **brief_message_kwargs(operation.name, content), ephemeral=True
            )
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)


class MissionActionButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"arma:mis:(?P<mid>[A-Z0-9\-]+):(?P<act>brief|obj|validate|publish|schedule)",
):
    _CONFIG = {
        "brief": ("📖", "View Brief", PermissionLevel.MEMBER),
        "obj": ("🎯", "Objectives", PermissionLevel.MEMBER),
        "validate": ("🧪", "Validate", PermissionLevel.MISSION_MAKER),
        "publish": ("📣", "Publish", PermissionLevel.MISSION_MAKER),
        "schedule": ("📅", "Schedule Operation", PermissionLevel.MISSION_MAKER),
    }

    def __init__(self, mission_id: str, action: str) -> None:
        emoji, label, _ = self._CONFIG[action]
        super().__init__(
            discord.ui.Button(
                label=label,
                emoji=emoji,
                style=discord.ButtonStyle.secondary,
                custom_id=f"arma:mis:{mission_id.upper()}:{action}",
            )
        )
        self.mission_id = mission_id.upper()
        self.action = action

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str]):
        return cls(match["mid"], match["act"])

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            await ensure_level(interaction, self._CONFIG[self.action][2])
            if self.action == "schedule":
                # Modals must be the first response — no defer here.
                from app.bot.views.operation_create import start_schedule_flow

                await start_schedule_flow(interaction, self.mission_id)
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            service = _mission_service(interaction)
            if self.action == "brief":
                entry = await service.get_mission(self.mission_id)
                title = entry.name if entry else self.mission_id
                content = await service.get_brief(self.mission_id)
                await interaction.followup.send(
                    **brief_message_kwargs(title, content), ephemeral=True
                )
            elif self.action == "obj":
                objectives = await service.get_objectives(self.mission_id)
                await interaction.followup.send(
                    embed=objectives_message_embed(self.mission_id, objectives), ephemeral=True
                )
            elif self.action == "validate":
                report = await service.validate_mission(self.mission_id)
                await interaction.followup.send(
                    embed=embeds.validation_embed(report), ephemeral=True
                )
            elif self.action == "publish":
                from app.bot.views.publish import continue_publish_flow

                await continue_publish_flow(interaction, self.mission_id)
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)


DYNAMIC_ITEMS = (AttendanceButton, RosterButton, OperationBriefButton, MissionActionButton)


def operation_post_view(operation: Operation) -> discord.ui.View | None:
    """Buttons for the operation post, appropriate to its lifecycle state."""
    if operation.status in (OperationStatus.CANCELLED.value, OperationStatus.COMPLETED.value):
        return None
    view = discord.ui.View(timeout=None)
    if operation.status == OperationStatus.OPEN.value:
        for status in ("attending", "maybe", "declined"):
            view.add_item(AttendanceButton(operation.id, status))
    view.add_item(RosterButton(operation.id))
    view.add_item(OperationBriefButton(operation.id))
    return view


def mission_post_view(mission_id: str) -> discord.ui.View:
    """Buttons on a published mission message."""
    view = discord.ui.View(timeout=None)
    view.add_item(MissionActionButton(mission_id, "brief"))
    view.add_item(MissionActionButton(mission_id, "obj"))
    view.add_item(MissionActionButton(mission_id, "schedule"))
    return view


def mission_detail_view(mission_id: str) -> discord.ui.View:
    """Buttons on /mission view — includes maker actions (gated at click)."""
    view = mission_post_view(mission_id)
    view.add_item(MissionActionButton(mission_id, "validate"))
    view.add_item(MissionActionButton(mission_id, "publish"))
    return view
