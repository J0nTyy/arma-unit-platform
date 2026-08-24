"""Controlled tools the AI assistant may call.

Architecture:   AI → Tool Registry → Application Services → Database/GitHub

The model only ever receives the structured result of an approved tool run
through the requester's permission level — it can never query SQL, see
documents above the caller's clearance, or perform writes (this phase is
strictly read-only). The registry, not the model, enforces every policy.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import timezone
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from app.bot.permissions import PermissionLevel
from app.knowledge import KnowledgeVisibility

if TYPE_CHECKING:
    from app.bot.bot import UnitBot

log = logging.getLogger(__name__)

_RESULT_CHAR_LIMIT = 4000


@dataclass(frozen=True)
class ToolContext:
    """Everything a tool may know about the requester — set by the app."""

    bot: "UnitBot"
    guild_id: int
    user_id: int
    level: PermissionLevel

    @property
    def knowledge_tier(self) -> KnowledgeVisibility:
        if self.level >= PermissionLevel.STAFF:
            return KnowledgeVisibility.STAFF
        if self.level >= PermissionLevel.MEMBER:
            return KnowledgeVisibility.MEMBER
        return KnowledgeVisibility.PUBLIC


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema
    required_level: PermissionLevel
    handler: Callable[[ToolContext, dict[str, Any]], Awaitable[str]]

    def wire_format(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


_NO_PARAMS = {"type": "object", "properties": {}, "additionalProperties": False}


def _params(**properties: dict) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


class ToolRegistry:
    def __init__(self, tools: list[ToolSpec]) -> None:
        self._tools = {tool.name: tool for tool in tools}

    def specs_for(self, level: PermissionLevel) -> list[dict[str, Any]]:
        return [
            tool.wire_format()
            for tool in self._tools.values()
            if level >= tool.required_level
        ]

    async def execute(self, name: str, arguments_json: str, context: ToolContext) -> str:
        """Run one tool call. Always returns a string for the model —
        including on authorization failure or handler errors."""
        tool = self._tools.get(name)
        if tool is None:
            return f"Error: unknown tool '{name}'."
        if context.level < tool.required_level:
            log.warning(
                "Tool %s denied for user %s (level %s)", name, context.user_id, context.level.name
            )
            return "Error: you are not authorized to use this tool."
        try:
            arguments = json.loads(arguments_json) if arguments_json.strip() else {}
            if not isinstance(arguments, dict):
                return "Error: tool arguments must be an object."
        except json.JSONDecodeError:
            return "Error: malformed tool arguments."
        try:
            result = await tool.handler(context, arguments)
        except Exception:  # noqa: BLE001 — tool failures must not kill the turn
            log.exception("Tool %s failed", name)
            return f"Error: the {name} tool failed. Tell the user this information is unavailable."
        return result[:_RESULT_CHAR_LIMIT]


# --- tool handlers ---------------------------------------------------------------


def _format_time(operation) -> str:
    moment = operation.scheduled_at
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return f"{moment:%Y-%m-%d %H:%M} UTC (unit timezone: {operation.timezone})"


async def _get_unit_information(context: ToolContext, _: dict) -> str:
    bot = context.bot
    configuration = await bot.guild_service.get_configuration(context.guild_id)
    lines = []
    if configuration is not None:
        lines.append(f"Unit name: {configuration.unit_name or configuration.guild_name}")
        if configuration.timezone:
            lines.append(f"Unit timezone: {configuration.timezone}")
    upcoming = await bot.operation_service.list_upcoming(context.guild_id)
    lines.append(f"Upcoming operations: {len(upcoming)}")
    if bot.knowledge_service is not None:
        document = await bot.knowledge_service.get_document("unit", context.knowledge_tier)
        if document is not None:
            lines.append(f"\nUnit overview:\n{document.content[:1800]}")
    return "\n".join(lines) if lines else "No unit information is configured yet."


async def _search_knowledge(context: ToolContext, arguments: dict) -> str:
    bot = context.bot
    if bot.knowledge_service is None:
        return "The knowledge base is not configured."
    query = str(arguments.get("query", ""))
    passages = await bot.knowledge_service.search(query, context.knowledge_tier)
    if not passages:
        return (
            "No matching unit documentation found. Tell the user the unit's "
            "documentation does not cover this."
        )
    blocks = []
    for passage in passages:
        heading = f" › {passage.heading}" if passage.heading else ""
        blocks.append(
            f"[source: {passage.title}{heading} ({passage.category})]\n{passage.text}"
        )
    return "\n\n---\n\n".join(blocks)


async def _search_missions(context: ToolContext, arguments: dict) -> str:
    service = context.bot.mission_service
    if service is None:
        return "The mission repository is not configured."
    entries = await service.search(str(arguments.get("query", "")))
    if not entries:
        return "No missions match that search."
    return "\n".join(
        f"{e.mission_id}: {e.name} — {e.status}, {e.map_name}, {e.mission_type}, "
        f"~{e.estimated_duration_minutes} min, by {e.mission_maker}"
        for e in entries[:10]
    )


async def _get_mission(context: ToolContext, arguments: dict) -> str:
    service = context.bot.mission_service
    if service is None:
        return "The mission repository is not configured."
    mission_id = str(arguments.get("mission_id", ""))
    entry = await service.get_mission(mission_id)
    if entry is None:
        return f"No mission with ID '{mission_id}' exists."
    lines = [
        f"{entry.mission_id}: {entry.name} (v{entry.version})",
        f"Status: {entry.status} | Map: {entry.map_name} | Type: {entry.mission_type} | "
        f"Difficulty: {entry.difficulty} | ~{entry.estimated_duration_minutes} min",
        f"Mission maker: {entry.mission_maker}",
        f"Description: {entry.description}",
    ]
    if entry.factions:
        lines.append("Factions: " + ", ".join(entry.factions))
    if entry.tags:
        lines.append("Tags: " + ", ".join(entry.tags))
    try:
        objectives = await service.get_objectives(entry.mission_id)
        lines.append(
            "Objectives: "
            + "; ".join(
                f"{o.name} ({o.type.value}{', required' if o.required else ''})"
                for o in objectives
            )
        )
    except Exception:  # noqa: BLE001 — objectives are a nice-to-have here
        pass
    return "\n".join(lines)


async def _get_mission_briefing(context: ToolContext, arguments: dict) -> str:
    service = context.bot.mission_service
    if service is None:
        return "The mission repository is not configured."
    mission_id = str(arguments.get("mission_id", ""))
    entry = await service.get_mission(mission_id)
    if entry is None:
        return f"No mission with ID '{mission_id}' exists."
    brief = await service.get_brief(entry.mission_id)
    suffix = "\n[briefing truncated]" if len(brief) > 3500 else ""
    return brief[:3500] + suffix


async def _get_upcoming_operations(context: ToolContext, _: dict) -> str:
    operations = await context.bot.operation_service.list_upcoming(context.guild_id)
    visible = [op for op in operations if op.message_id is not None or op.status != "scheduled"]
    if not visible:
        return "There are no upcoming operations scheduled."
    lines = []
    for operation in visible:
        counts = await context.bot.operation_service.attendance_counts(operation.id)
        lines.append(
            f"#{operation.id}: {operation.name} (mission {operation.mission_id}) — "
            f"{_format_time(operation)} — status: {operation.status} — "
            f"{counts.get('attending', 0)} attending, {counts.get('maybe', 0)} maybe"
        )
    return "\n".join(lines)


async def _get_operation(context: ToolContext, arguments: dict) -> str:
    try:
        operation_id = int(arguments.get("operation_id", 0))
    except (TypeError, ValueError):
        return "Error: operation_id must be a number."
    operation = await context.bot.operation_service.get(operation_id)
    if operation.guild_id != context.guild_id:
        return "No such operation in this server."
    counts = await context.bot.operation_service.attendance_counts(operation.id)
    lines = [
        f"Operation #{operation.id}: {operation.name}",
        f"Mission: {operation.mission_id} | Status: {operation.status}",
        f"When: {_format_time(operation)}",
        f"Attendance: {counts.get('attending', 0)} attending, "
        f"{counts.get('maybe', 0)} maybe, {counts.get('declined', 0)} declined",
    ]
    if operation.objectives_snapshot:
        lines.append(f"Objectives:\n{operation.objectives_snapshot}")
    return "\n".join(lines)


async def _get_operation_roster(context: ToolContext, arguments: dict) -> str:
    try:
        operation_id = int(arguments.get("operation_id", 0))
    except (TypeError, ValueError):
        return "Error: operation_id must be a number."
    operation = await context.bot.operation_service.get(operation_id)
    if operation.guild_id != context.guild_id:
        return "No such operation in this server."
    roster = await context.bot.operation_service.roster(operation_id)

    def names(records) -> str:
        return ", ".join(record.display_name for record in records) or "nobody yet"

    lines = [
        f"Roster for {operation.name}:",
        f"Attending ({len(roster.attending)}): {names(roster.attending)}",
        f"Maybe ({len(roster.maybe)}): {names(roster.maybe)}",
    ]
    if context.level >= PermissionLevel.STAFF:
        # Staff view: who explicitly declined (members only see the count)
        lines.append(f"Declined ({len(roster.declined)}): {names(roster.declined)}")
    else:
        lines.append(f"Declined: {len(roster.declined)} member(s)")
    if roster.waitlist:
        lines.append(f"Waitlist ({len(roster.waitlist)}): {names(roster.waitlist)}")
    return "\n".join(lines)


def _format_profile_lines(player, qualifications, *, include_private: bool) -> list[str]:
    from app.database.models.player import QUALIFICATIONS, ROLE_PREFERENCES

    lines = [
        f"Display name: {player.display_name}",
        f"Status: {player.active_status}",
        f"Member since: {player.join_date:%Y-%m-%d}",
    ]
    roles = [
        ROLE_PREFERENCES.get(role, role)
        for role in (player.primary_role, player.secondary_role)
        if role
    ]
    lines.append("Role preferences: " + (", ".join(roles) if roles else "not set"))
    if qualifications:
        lines.append(
            "Qualifications: "
            + ", ".join(QUALIFICATIONS.get(q.qualification, q.qualification) for q in qualifications)
        )
    else:
        lines.append("Qualifications: none yet")
    if player.bio:
        lines.append(f"Bio: {player.bio}")
    if include_private and player.timezone:
        lines.append(f"Timezone: {player.timezone}")
    return lines


async def _get_my_profile(context: ToolContext, _: dict) -> str:
    """The requester's OWN profile — full detail is allowed by definition."""
    bot = context.bot
    player = await bot.player_service.get(context.guild_id, context.user_id)
    if player is None:
        return (
            "The user has no unit profile yet. Tell them to run /profile once to "
            "create it, and the Set up button to fill in preferences."
        )
    qualifications = await bot.player_service.qualifications(player.id)
    lines = _format_profile_lines(player, qualifications, include_private=True)
    stats = await bot.attendance_service.player_stats(context.guild_id, context.user_id)
    lines.append(
        f"Participation: {stats.signups} signups, {stats.attended} attended, "
        f"{stats.absent} absent, {stats.excused} excused"
        + (f", attendance rate {stats.rate:.0f}%" if stats.rate is not None else "")
    )
    history = await bot.attendance_service.recent_history(context.guild_id, context.user_id)
    if history:
        lines.append(
            "Recent: " + "; ".join(f"{name} — {status}" for name, _, status in history)
        )
    return "\n".join(lines)


async def _get_member_profile(context: ToolContext, arguments: dict) -> str:
    """Another member's profile — the app enforces the unit's visibility
    policy (minimal): no participation data unless the requester is staff."""
    bot = context.bot
    query = str(arguments.get("name", "")).strip()
    if not query:
        return "Error: provide the member's name."
    matches = await bot.player_service.search_members(context.guild_id, query, limit=3)
    if not matches:
        return f"No unit member matches '{query}'."
    player = matches[0]
    if player.discord_user_id == context.user_id:
        return await _get_my_profile(context, {})
    qualifications = await bot.player_service.qualifications(player.id)
    lines = _format_profile_lines(player, qualifications, include_private=False)
    if context.level >= PermissionLevel.STAFF:
        stats = await bot.attendance_service.player_stats(
            context.guild_id, player.discord_user_id
        )
        lines.append(
            f"[staff] Participation: {stats.attended} attended, {stats.absent} absent, "
            f"{stats.excused} excused"
            + (f", rate {stats.rate:.0f}%" if stats.rate is not None else "")
        )
        lines.append(f"[staff] Onboarding: {player.onboarding_status}")
    else:
        lines.append(
            "Participation details are private (visible to the member themself and staff). "
            "If asked, say attendance information isn't shared between members."
        )
    if len(matches) > 1:
        lines.append(
            "Other possible matches: " + ", ".join(m.display_name for m in matches[1:])
        )
    return "\n".join(lines)


async def _get_unit_statistics(context: ToolContext, _: dict) -> str:
    stats = await context.bot.attendance_service.unit_stats(context.guild_id)
    lines = [
        f"Active members: {stats.active_members}",
        f"Operations completed: {stats.operations_completed}",
        f"Operations this month: {stats.operations_this_month}",
    ]
    if stats.average_attended_per_operation is not None:
        lines.append(
            f"Average attendance: {stats.average_attended_per_operation:.1f} players per operation"
        )
    if stats.overall_attendance_rate is not None:
        lines.append(f"Unit attendance rate: {stats.overall_attendance_rate:.0f}%")
    if stats.most_attended:
        lines.append(f"Most attended operation: {stats.most_attended[0]} ({stats.most_attended[1]})")
    return "\n".join(lines)


async def _get_attendance_leaders(context: ToolContext, _: dict) -> str:
    from datetime import datetime, timezone

    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    leaders = await context.bot.attendance_service.attendance_leaders(
        context.guild_id, month_start
    )
    if not leaders:
        return "No finalized attendance records this month."
    return "Top attendance this month:\n" + "\n".join(
        f"{i + 1}. {name} — {count} attended" for i, (name, count) in enumerate(leaders)
    )


def build_default_registry() -> ToolRegistry:
    member = PermissionLevel.MEMBER
    return ToolRegistry(
        [
            ToolSpec(
                "get_unit_information",
                "Basic information about this unit: name, timezone, overview, "
                "how many operations are coming up.",
                _NO_PARAMS, member, _get_unit_information,
            ),
            ToolSpec(
                "search_knowledge",
                "Search the unit's documentation: rules, onboarding guides, SOPs, "
                "lore, FAQs, mod setup, radio usage. Use this for any question about "
                "how the unit works or its story.",
                _params(query={"type": "string", "description": "Search terms"}),
                member, _search_knowledge,
            ),
            ToolSpec(
                "search_missions",
                "Search the unit's mission library by name, map, type, tag or maker.",
                _params(query={"type": "string", "description": "Search terms"}),
                member, _search_missions,
            ),
            ToolSpec(
                "get_mission",
                "Full details of one mission by its ID (e.g. OP-002): metadata and objectives.",
                _params(mission_id={"type": "string", "description": "Mission ID like OP-002"}),
                member, _get_mission,
            ),
            ToolSpec(
                "get_mission_briefing",
                "The full text of a mission's briefing document.",
                _params(mission_id={"type": "string", "description": "Mission ID like OP-002"}),
                member, _get_mission_briefing,
            ),
            ToolSpec(
                "get_upcoming_operations",
                "List the currently scheduled upcoming operations with dates and signups.",
                _NO_PARAMS, member, _get_upcoming_operations,
            ),
            ToolSpec(
                "get_operation",
                "Details of one scheduled operation by its number.",
                _params(operation_id={"type": "integer", "description": "Operation number"}),
                member, _get_operation,
            ),
            ToolSpec(
                "get_operation_roster",
                "Who has responded to an operation (attendance lists).",
                _params(operation_id={"type": "integer", "description": "Operation number"}),
                member, _get_operation_roster,
            ),
            ToolSpec(
                "get_my_profile",
                "The requesting user's OWN unit profile: roles, join date, "
                "qualifications, and their personal attendance record. Use for any "
                "'my profile / my attendance / my roles' question.",
                _NO_PARAMS, member, _get_my_profile,
            ),
            ToolSpec(
                "get_member_profile",
                "Another unit member's profile by name. Returns only what the "
                "requester is allowed to see (participation data is private).",
                _params(name={"type": "string", "description": "Member display name"}),
                member, _get_member_profile,
            ),
            ToolSpec(
                "get_unit_statistics",
                "Unit-wide participation statistics: member count, operations "
                "completed, average attendance.",
                _NO_PARAMS, member, _get_unit_statistics,
            ),
            ToolSpec(
                "get_attendance_leaders",
                "Staff only: highest attendance counts this month.",
                _NO_PARAMS, PermissionLevel.STAFF, _get_attendance_leaders,
            ),
        ]
    )
