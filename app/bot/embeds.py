"""Shared Discord embed builders.

Every place a mission or operation is rendered (published posts, ephemeral
views, previews, updates) uses these builders, so the look stays consistent
and updates never drift from the original post.

Mission makers write plain Markdown and JSON in the missions repo — all
Discord presentation (layout, emoji, sections, columns) happens here.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import discord

from app.database.models.mission import MissionIndexEntry
from app.database.models.operation import Operation, OperationStatus
from app.missions import Objective, ObjectiveType, ValidationReport
from app.services.operations import Roster

GREEN = discord.Colour.from_str("#43b581")
RED = discord.Colour.from_str("#f04747")
ORANGE = discord.Colour.from_str("#faa61a")
BLURPLE = discord.Colour.blurple()
GREY = discord.Colour.from_str("#747f8d")
NAVY = discord.Colour.from_str("#2c3e50")

DIVIDER = "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"

MISSION_STATUS_BADGE = {
    "draft": "📝 DRAFT",
    "development": "🟡 IN DEVELOPMENT",
    "review": "🔵 IN REVIEW",
    "ready": "🟢 READY",
    "archived": "⚫ ARCHIVED",
}
MISSION_STATUS_COLOUR = {
    "draft": GREY,
    "development": ORANGE,
    "review": BLURPLE,
    "ready": GREEN,
    "archived": GREY,
}

OPERATION_STATUS_BADGE = {
    OperationStatus.SCHEDULED.value: "🗓️ SCHEDULED",
    OperationStatus.OPEN.value: "🟢 SIGNUPS OPEN",
    OperationStatus.LOCKED.value: "🔒 SIGNUPS LOCKED",
    OperationStatus.ACTIVE.value: "🔵 OPERATION IN PROGRESS",
    OperationStatus.COMPLETED.value: "✅ COMPLETED",
    OperationStatus.CANCELLED.value: "🔴 CANCELLED",
}
OPERATION_STATUS_COLOUR = {
    OperationStatus.SCHEDULED.value: BLURPLE,
    OperationStatus.OPEN.value: GREEN,
    OperationStatus.LOCKED.value: ORANGE,
    OperationStatus.ACTIVE.value: BLURPLE,
    OperationStatus.COMPLETED.value: GREY,
    OperationStatus.CANCELLED.value: RED,
}

_OBJECTIVE_ICON = {
    ObjectiveType.PRIMARY: "🎯",
    ObjectiveType.SECONDARY: "🔸",
    ObjectiveType.OPTIONAL: "◽",
}

# Emoji for well-known briefing sections; anything unknown gets a neutral dot.
_BRIEF_SECTION_EMOJI = {
    "situation": "🧭",
    "background": "📜",
    "mission": "🎯",
    "objectives": "✅",
    "rules": "⚖️",
    "rules / restrictions": "⚖️",
    "restrictions": "⚖️",
    "equipment": "🎒",
    "intelligence": "🕵️",
    "execution": "🗺️",
    "extraction": "🚁",
}
_MAKER_NOTES_HEADING = "notes for mission makers"


def _utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def unix_ts(moment: datetime) -> int:
    """Unix timestamp for Discord <t:...> markup (treats naive values as UTC)."""
    return int(_utc(moment).timestamp())


def render_objectives(objectives: list[Objective] | None) -> str | None:
    """Compact objectives block used in mission and operation posts."""
    if not objectives:
        return None
    lines = [
        f"{_OBJECTIVE_ICON.get(o.type, '•')} {o.name}" for o in objectives[:8]
    ]
    if len(objectives) > 8:
        lines.append(f"… and {len(objectives) - 8} more")
    return "\n".join(lines)


# --- missions ---------------------------------------------------------------


def mission_embed(
    entry: MissionIndexEntry, objectives: list[Objective] | None = None
) -> discord.Embed:
    """The polished mission post used in channels and detail views."""
    night = "night" in (entry.tags or [])
    embed = discord.Embed(
        title=f"🎯 {entry.name.upper()}",
        description=(
            f"**{entry.mission_type} · {entry.map_name} · {entry.difficulty.title()}**\n\n"
            f"> {entry.description}"
        ),
        colour=MISSION_STATUS_COLOUR.get(entry.status, BLURPLE),
    )
    embed.add_field(
        name="Status", value=MISSION_STATUS_BADGE.get(entry.status, entry.status), inline=True
    )
    embed.add_field(name="Mission maker", value=entry.mission_maker, inline=True)
    embed.add_field(
        name="Duration",
        value=f"⏱ ~{entry.estimated_duration_minutes} min" + (" · 🌙 night" if night else ""),
        inline=True,
    )

    objectives_block = render_objectives(objectives)
    if objectives_block:
        embed.add_field(name="🎯 Objectives", value=objectives_block, inline=False)
    if entry.factions:
        embed.add_field(name="Factions", value=", ".join(entry.factions), inline=True)
    if not entry.is_valid:
        problems = "\n".join(f"✗ {error}" for error in entry.validation_errors[:3])
        embed.add_field(name="⚠️ Fails validation", value=problems[:1024], inline=False)
    tags = " · ".join(entry.tags) if entry.tags else "no tags"
    embed.set_footer(text=f"{entry.mission_id} · v{entry.version} · {tags}")
    return embed


def mission_line(entry: MissionIndexEntry) -> str:
    """One-mission summary line for list embeds."""
    badge = MISSION_STATUS_BADGE.get(entry.status, entry.status)
    flag = "" if entry.is_valid else " ⚠️"
    return (
        f"**{entry.mission_id} — {entry.name}**{flag}\n"
        f"{badge} · {entry.map_name} · {entry.mission_type} · "
        f"~{entry.estimated_duration_minutes} min"
    )


# --- operations ---------------------------------------------------------------


def _attendance_column(records: list, cap: int = 12) -> str:
    if not records:
        return "*—*"
    lines = [f"<@{record.user_id}>" for record in records[:cap]]
    if len(records) > cap:
        lines.append(f"*+{len(records) - cap} more*")
    return "\n".join(lines)


def operation_embed(
    operation: Operation,
    mission: MissionIndexEntry | None,
    roster: Roster | None,
) -> discord.Embed:
    """The central operation post: header, briefing summary, objectives, and
    a three-column live attendance board."""
    badge = OPERATION_STATUS_BADGE.get(operation.status, operation.status.upper())
    unix = unix_ts(operation.scheduled_at)

    header_lines = [
        f"**{badge}**",
        DIVIDER,
        f"📅 **<t:{unix}:F>**  ·  ⏳ <t:{unix}:R>",
    ]
    if mission is not None:
        night = "night" in (mission.tags or [])
        facts = f"🗺️ **{mission.map_name}**  ·  ⚔️ {mission.mission_type}  ·  💀 {mission.difficulty.title()}"
        if night:
            facts += "  ·  🌙 Night"
        header_lines.append(facts)
    if mission is not None:
        header_lines += ["", f"> *{mission.description}*"]

    embed = discord.Embed(
        title=f"⚔️  {operation.name.upper()}",
        description="\n".join(header_lines),
        colour=OPERATION_STATUS_COLOUR.get(operation.status, BLURPLE),
    )
    if operation.objectives_snapshot:
        embed.add_field(
            name="🎯 OBJECTIVES",
            value=operation.objectives_snapshot[:1024],
            inline=False,
        )

    attending = roster.attending if roster else []
    maybe = roster.maybe if roster else []
    declined = roster.declined if roster else []
    embed.add_field(
        name=f"{DIVIDER}\n🪖 ATTENDANCE — {len(attending)} confirmed",
        value="​",
        inline=False,
    )
    embed.add_field(
        name=f"🟢 Attending ({len(attending)})",
        value=_attendance_column(attending),
        inline=True,
    )
    embed.add_field(
        name=f"🟡 Maybe ({len(maybe)})", value=_attendance_column(maybe), inline=True
    )
    embed.add_field(
        name=f"🔴 Can't attend ({len(declined)})",
        value=_attendance_column(declined),
        inline=True,
    )
    if roster and roster.waitlist:
        waitlist = "\n".join(
            f"{i + 1}. <@{record.user_id}>" for i, record in enumerate(roster.waitlist[:10])
        )
        embed.add_field(name=f"⏳ Waitlist ({len(roster.waitlist)})", value=waitlist, inline=False)

    maker = f" · made by {mission.mission_maker}" if mission else ""
    embed.set_footer(
        text=f"Operation #{operation.id} · {operation.mission_id}{maker} · "
        "times shown in your local timezone"
    )
    return embed


def roster_embed(operation: Operation, roster: Roster) -> discord.Embed:
    def block(records, *, numbered: bool = False, cap: int = 30) -> str:
        if not records:
            return "*nobody yet*"
        lines = [
            (f"{i + 1}. " if numbered else "• ") + record.display_name
            for i, record in enumerate(records[:cap])
        ]
        if len(records) > cap:
            lines.append(f"… and {len(records) - cap} more")
        return "\n".join(lines)

    embed = discord.Embed(
        title=f"👥 Roster — {operation.name}",
        colour=OPERATION_STATUS_COLOUR.get(operation.status, BLURPLE),
    )
    embed.add_field(
        name=f"🟢 Attending — {len(roster.attending)}",
        value=block(roster.attending),
        inline=False,
    )
    if roster.waitlist:
        embed.add_field(
            name=f"⏳ Waitlist — {len(roster.waitlist)}",
            value=block(roster.waitlist, numbered=True),
            inline=False,
        )
    embed.add_field(name=f"🟡 Maybe — {len(roster.maybe)}", value=block(roster.maybe), inline=False)
    embed.add_field(
        name=f"🔴 Not attending — {len(roster.declined)}",
        value=str(len(roster.declined)),
        inline=False,
    )
    return embed


def operation_line(operation: Operation) -> str:
    unix = unix_ts(operation.scheduled_at)
    badge = OPERATION_STATUS_BADGE.get(operation.status, operation.status)
    return (
        f"**{operation.name}** — {operation.mission_id}\n"
        f"{badge} · <t:{unix}:F> (<t:{unix}:R>)"
    )


# --- briefings -----------------------------------------------------------------

_SECTION_RE = re.compile(r"^##\s+(?P<heading>.+?)\s*$", re.MULTILINE)
_FIELD_LIMIT = 1024
_EMBED_BUDGET = 5200  # keep headroom under Discord's 6000-char message budget


def _split_value(text: str) -> list[str]:
    """Split long section text into <=1024-char chunks on line boundaries."""
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > _FIELD_LIMIT:
            if current:
                chunks.append(current)
            while len(line) > _FIELD_LIMIT:  # pathological single line
                chunks.append(line[:_FIELD_LIMIT])
                line = line[_FIELD_LIMIT:]
            current = line
        else:
            current = candidate
    if current.strip():
        chunks.append(current)
    return chunks


def brief_embeds(title: str, content: str, *, include_maker_notes: bool = False) -> list[discord.Embed]:
    """Render a plain-Markdown briefing as polished Discord embeds.

    Sections (## headings) become titled fields with themed emoji; the
    'Notes for Mission Makers' section is omitted from player-facing posts.
    Returns 1..n embeds, each under Discord's size budget.
    """
    content = content.strip()
    # Drop the top-level "# Operation Name" line — the embed title covers it.
    content = re.sub(r"^#\s+.+?\n", "", content, count=1)

    sections: list[tuple[str | None, str]] = []
    last_end = 0
    last_heading: str | None = None
    for match in _SECTION_RE.finditer(content):
        sections.append((last_heading, content[last_end:match.start()].strip()))
        last_heading = match.group("heading")
        last_end = match.end()
    sections.append((last_heading, content[last_end:].strip()))

    embeds: list[discord.Embed] = []
    embed = discord.Embed(title=f"📖  {title.upper()} — BRIEFING", colour=NAVY)
    size = len(embed.title or "")

    def flush() -> None:
        nonlocal embed, size
        if embed.fields or embed.description:
            embeds.append(embed)
        embed = discord.Embed(colour=NAVY)
        size = 0

    for heading, body in sections:
        if not body:
            continue
        if heading and heading.strip().lower().startswith(_MAKER_NOTES_HEADING) and not include_maker_notes:
            continue
        if heading is None:
            embed.description = body[:4000]
            size += len(embed.description)
            continue
        emoji = _BRIEF_SECTION_EMOJI.get(heading.strip().lower(), "▫️")
        chunks = _split_value(body)
        for index, chunk in enumerate(chunks):
            name = f"{emoji}  {heading.upper()}" if index == 0 else "​"
            if size + len(chunk) + len(name) > _EMBED_BUDGET or len(embed.fields) >= 24:
                flush()
            embed.add_field(name=name, value=chunk, inline=False)
            size += len(chunk) + len(name)
    flush()
    return embeds or [discord.Embed(title=f"📖  {title.upper()} — BRIEFING", colour=NAVY)]


# --- validation ----------------------------------------------------------------


def validation_embed(report: ValidationReport) -> discord.Embed:
    lines = [f"✓ {name}" for name in report.passed]
    lines += [f"✗ {error}" for error in report.errors]
    lines += [f"⚠ {warning}" for warning in report.warnings]
    if report.metadata is not None:
        header = f"**{report.metadata.id} — {report.metadata.name}**\nVersion {report.metadata.version}"
    else:
        header = f"**{report.directory}**"
    return discord.Embed(
        title="🟢 Mission valid" if report.is_valid else "🔴 Mission invalid",
        description=f"{header}\n\n" + "\n".join(lines)[:3900],
        colour=GREEN if report.is_valid else RED,
    )
