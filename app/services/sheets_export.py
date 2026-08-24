"""Google Sheets export — the unit's data, mirrored to a staff spreadsheet.

Five tabs, each fully rewritten on every export (idempotent, no drift):

    Members        — profiles, preferences, certs, participation
    Operations     — every operation with signup/attended counts
    Attendance Log — one row per finalized verdict (who, what, by whom)
    Certifications — one row per granted cert (who, what, trainer, when)
    Missions       — the mission library index

Triggered by /unit sheets (staff) and automatically once a day. Who can SEE
the sheet is decided in Google (share it with staff emails); the bot only
needs its service account shared as Editor.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.database import Database
from app.database.models.mission import MissionIndexEntry
from app.database.models.operation import Operation, OperationAttendance
from app.database.models.player import (
    QUALIFICATIONS,
    ROLE_PREFERENCES,
    AttendanceRecord,
    Player,
    PlayerQualification,
)
from app.errors import DatabaseError
from app.integrations.sheets import SheetsClient

log = logging.getLogger(__name__)


def _when(moment: datetime | None) -> str:
    return f"{moment:%Y-%m-%d %H:%M} UTC" if moment else ""


def _role(slug: str | None) -> str:
    return ROLE_PREFERENCES.get(slug, slug or "").split(" ", 1)[-1] if slug else ""


class SheetExportService:
    def __init__(self, database: Database, client: SheetsClient) -> None:
        self._database = database
        self._client = client

    @property
    def url(self) -> str:
        return self._client.url

    async def export_all(self, guild_id: int) -> dict[str, int]:
        """Rebuild every tab. Returns {tab: row count}."""
        try:
            async with self._database.session() as session:
                players = list(
                    (
                        await session.execute(
                            select(Player)
                            .where(Player.guild_id == guild_id)
                            .order_by(Player.display_name)
                        )
                    ).scalars()
                )
                qualifications = (
                    await session.execute(
                        select(PlayerQualification, Player)
                        .join(Player, PlayerQualification.player_id == Player.id)
                        .where(Player.guild_id == guild_id)
                        .order_by(PlayerQualification.granted_at)
                    )
                ).all()
                operations = list(
                    (
                        await session.execute(
                            select(Operation)
                            .where(Operation.guild_id == guild_id)
                            .order_by(Operation.scheduled_at)
                        )
                    ).scalars()
                )
                signup_counts = {
                    row[0]: row[1]
                    for row in (
                        await session.execute(
                            select(OperationAttendance.operation_id, func.count())
                            .join(Operation, OperationAttendance.operation_id == Operation.id)
                            .where(
                                Operation.guild_id == guild_id,
                                OperationAttendance.status.in_(("attending", "waitlist")),
                            )
                            .group_by(OperationAttendance.operation_id)
                        )
                    ).all()
                }
                records = (
                    await session.execute(
                        select(AttendanceRecord, Player, Operation)
                        .join(Player, AttendanceRecord.player_id == Player.id)
                        .join(Operation, AttendanceRecord.operation_id == Operation.id)
                        .where(Operation.guild_id == guild_id)
                        .order_by(Operation.scheduled_at, Player.display_name)
                    )
                ).all()
                missions = list(
                    (
                        await session.execute(
                            select(MissionIndexEntry).order_by(MissionIndexEntry.mission_id)
                        )
                    ).scalars()
                )
        except SQLAlchemyError as exc:
            raise DatabaseError("sheet export queries failed") from exc

        certs_by_player: dict[int, list[str]] = {}
        for qualification, player in qualifications:
            certs_by_player.setdefault(player.id, []).append(
                QUALIFICATIONS.get(qualification.qualification, qualification.qualification)
            )
        verdicts_by_player: dict[int, dict[str, int]] = {}
        attended_by_operation: dict[int, int] = {}
        for record, player, operation in records:
            verdicts = verdicts_by_player.setdefault(player.id, {})
            verdicts[record.status] = verdicts.get(record.status, 0) + 1
            if record.status == "attended":
                attended_by_operation[operation.id] = (
                    attended_by_operation.get(operation.id, 0) + 1
                )

        member_rows = []
        for player in players:
            verdicts = verdicts_by_player.get(player.id, {})
            attended, absent = verdicts.get("attended", 0), verdicts.get("absent", 0)
            rate = f"{attended / (attended + absent) * 100:.0f}%" if attended + absent else ""
            member_rows.append([
                player.display_name, str(player.discord_user_id), player.active_status,
                player.onboarding_status, _when(player.join_date),
                _role(player.primary_role), _role(player.secondary_role),
                player.arma_experience or "", player.timezone or "",
                player.steam_id or "", ", ".join(certs_by_player.get(player.id, [])),
                attended, absent, verdicts.get("excused", 0), rate,
                "left server" if player.left_at else "",
            ])

        operation_rows = [
            [
                operation.id, operation.name, operation.mission_id,
                _when(operation.scheduled_at), operation.timezone, operation.status,
                signup_counts.get(operation.id, 0),
                attended_by_operation.get(operation.id, 0),
            ]
            for operation in operations
        ]
        attendance_rows = [
            [
                _when(operation.scheduled_at), operation.name, operation.mission_id,
                player.display_name, record.status,
                str(record.finalized_by), _when(record.finalized_at),
            ]
            for record, player, operation in records
        ]
        certification_rows = [
            [
                player.display_name,
                QUALIFICATIONS.get(qualification.qualification, qualification.qualification),
                str(qualification.granted_by), _when(qualification.granted_at),
                _when(qualification.expires_at),
            ]
            for qualification, player in qualifications
        ]
        mission_rows = [
            [
                mission.mission_id, mission.name, mission.status, mission.map_name,
                mission.mission_type, mission.difficulty,
                mission.estimated_duration_minutes, mission.mission_maker,
                mission.version, "yes" if mission.is_valid else "NO",
                _when(mission.synced_at),
            ]
            for mission in missions
        ]

        tabs: list[tuple[str, list[str], list[list]]] = [
            ("Members", [
                "Name", "Discord ID", "Status", "Onboarding", "Joined",
                "Primary role", "Secondary role", "Experience", "Timezone",
                "Steam ID", "Certifications", "Attended", "Absent", "Excused",
                "Attendance rate", "Notes",
            ], member_rows),
            ("Operations", [
                "#", "Name", "Mission", "Scheduled (UTC)", "Unit TZ", "Status",
                "Signed up", "Attended",
            ], operation_rows),
            ("Attendance Log", [
                "Operation date", "Operation", "Mission", "Member", "Verdict",
                "Finalized by (Discord ID)", "Finalized at",
            ], attendance_rows),
            ("Certifications", [
                "Member", "Certification", "Granted by (Discord ID)", "Granted at",
                "Expires",
            ], certification_rows),
            ("Missions", [
                "ID", "Name", "Status", "Map", "Type", "Difficulty",
                "Duration (min)", "Maker", "Version", "Valid", "Last synced",
            ], mission_rows),
        ]
        results: dict[str, int] = {}
        for title, headers, rows in tabs:
            results[title] = await asyncio.to_thread(
                self._client.replace_worksheet, title, headers, rows
            )
        log.info("Sheets export complete for guild %s: %s", guild_id, results)
        return results
