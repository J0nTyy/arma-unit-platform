"""The unit's data as human-readable tables and snapshots.

The database stays canonical; this service turns it into files people can
open in Excel/LibreOffice, written into each server's isolated data
directory (see data/README.md):

    exports/unit-data_<date>.xlsx    /unit export — ONE workbook, one sheet
                                     per dataset; never overwritten; only
                                     the newest few are kept
    exports/latest/<name>.csv        current-state snapshots, regenerated
                                     in place (daily + on every export)
    memory/memories.md               readable view of the assistant's memory

Datasets (each attendance record is ONE ROW — filterable, sortable,
export-friendly; never one giant row per player):

    members         profiles, preferences, certs, participation
    operations      every operation with signup/attended counts
    attendance      one row per finalized verdict incl. signup + role
    certifications  one row per granted certification
    missions        the mission library index
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.database import Database
from app.database.models.memory import BotMemory
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
from app.services.exports import ExportService

log = logging.getLogger(__name__)

Dataset = tuple[list[str], list[list]]

_WORKBOOK_NAME = "unit-data"
_KEEP_DATED_WORKBOOKS = 10  # older /unit export files are deleted automatically


def _when(moment: datetime | None) -> str:
    return f"{moment:%Y-%m-%d %H:%M} UTC" if moment else ""


def _role(slug: str | None) -> str:
    return ROLE_PREFERENCES.get(slug, slug or "").split(" ", 1)[-1] if slug else ""


class DataExportService:
    def __init__(self, database: Database, exporter: ExportService | None = None) -> None:
        self._database = database
        self._exporter = exporter or ExportService()

    # --- datasets (pure queries → headers + rows) -----------------------------

    async def datasets(self, guild_id: int) -> dict[str, Dataset]:
        """Build every dataset for one guild. Guild-scoped by construction."""
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
                signups = (
                    await session.execute(
                        select(OperationAttendance)
                        .join(Operation, OperationAttendance.operation_id == Operation.id)
                        .where(Operation.guild_id == guild_id)
                    )
                ).scalars()
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
            raise DatabaseError("export queries failed") from exc

        signup_by_key: dict[tuple[int, int], str] = {}
        signup_counts: dict[int, int] = {}
        for signup in signups:
            signup_by_key[(signup.operation_id, signup.user_id)] = signup.status
            if signup.status in ("attending", "waitlist"):
                signup_counts[signup.operation_id] = signup_counts.get(signup.operation_id, 0) + 1

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
        # One row per attendance record — the spec's table shape:
        # Player | Operation | Date | Signup | Final status | Role | Notes
        attendance_rows = [
            [
                player.display_name, operation.name, operation.mission_id,
                _when(operation.scheduled_at),
                signup_by_key.get((operation.id, player.discord_user_id), ""),
                record.status, _role(player.primary_role), "",
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

        return {
            "members": ([
                "Name", "Discord ID", "Status", "Onboarding", "Joined",
                "Primary role", "Secondary role", "Experience", "Timezone",
                "Steam ID", "Certifications", "Attended", "Absent", "Excused",
                "Attendance rate", "Notes",
            ], member_rows),
            "operations": ([
                "#", "Name", "Mission", "Scheduled (UTC)", "Unit TZ", "Status",
                "Signed up", "Attended",
            ], operation_rows),
            "attendance": ([
                "Player", "Operation", "Mission", "Operation date", "Signup",
                "Final status", "Role", "Notes", "Finalized by (Discord ID)",
                "Finalized at",
            ], attendance_rows),
            "certifications": ([
                "Member", "Certification", "Granted by (Discord ID)", "Granted at",
                "Expires",
            ], certification_rows),
            "missions": ([
                "ID", "Name", "Status", "Map", "Type", "Difficulty",
                "Duration (min)", "Maker", "Version", "Valid", "Last synced",
            ], mission_rows),
        }

    # --- writing to a server's data directory ---------------------------------

    async def export_workbook(
        self, guild_id: int, exports_dir: Path
    ) -> tuple[Path, dict[str, int]]:
        """Staff-triggered export: ONE dated Excel workbook (one sheet per
        dataset), never overwritten. Old workbooks beyond the newest
        _KEEP_DATED_WORKBOOKS are deleted so the folder can't fill up, and
        the exports/latest/ CSVs are refreshed at the same time.

        Returns (workbook path, {dataset: row count}).
        """
        datasets = await self.datasets(guild_id)
        sheets = {
            name.capitalize(): (headers, rows)
            for name, (headers, rows) in datasets.items()
        }
        path = await asyncio.to_thread(
            self._exporter.dated_workbook, exports_dir, _WORKBOOK_NAME, sheets
        )
        removed = await asyncio.to_thread(
            self._exporter.prune_dated, exports_dir, _WORKBOOK_NAME,
            _KEEP_DATED_WORKBOOKS,
        )
        await asyncio.to_thread(self._write_latest, datasets, exports_dir)
        counts = {name: len(rows) for name, (_, rows) in datasets.items()}
        log.info(
            "Export for guild %s -> %s (%s)%s",
            guild_id, path.name, counts,
            f"; pruned {len(removed)} old export(s)" if removed else "",
        )
        return path, counts

    def _write_latest(self, datasets: dict[str, Dataset], exports_dir: Path) -> None:
        latest = exports_dir / "latest"
        for name, (headers, rows) in datasets.items():
            self._exporter.snapshot(latest, name, headers, rows)

    async def write_snapshots(self, guild_id: int, exports_dir: Path) -> dict[str, int]:
        """Regenerate the 'latest state' CSVs (exports/latest/, overwritten)."""
        datasets = await self.datasets(guild_id)
        await asyncio.to_thread(self._write_latest, datasets, exports_dir)
        return {name: len(rows) for name, (_, rows) in datasets.items()}

    async def write_memory_snapshot(self, guild_id: int, memory_dir: Path) -> Path:
        """Readable Markdown view of the assistant's server memory.

        Generated + overwritten; the database stays canonical. Staff manage
        entries with /unit memories, not by editing this file.
        """
        try:
            async with self._database.session() as session:
                memories = list(
                    (
                        await session.execute(
                            select(BotMemory)
                            .where(BotMemory.guild_id == guild_id)
                            .order_by(BotMemory.created_at)
                        )
                    ).scalars()
                )
                total = (
                    await session.execute(
                        select(func.count()).select_from(BotMemory).where(
                            BotMemory.guild_id == guild_id
                        )
                    )
                ).scalar_one()
        except SQLAlchemyError as exc:
            raise DatabaseError("memory snapshot query failed") from exc

        lines = [
            "# Assistant server memory (generated snapshot)",
            "",
            "The database is canonical — manage entries with `/unit memories` in",
            "Discord. This file is regenerated and overwritten automatically.",
            "",
            f"{total} entries.",
            "",
        ]
        for memory in memories:
            meta = [f"#{memory.id}", _when(memory.created_at)]
            if memory.visibility != "unit":
                meta.append(f"visibility: {memory.visibility}")
            if memory.expires_at:
                meta.append(f"expires: {_when(memory.expires_at)}")
            lines.append(f"- {memory.content}  \n  _{' · '.join(part for part in meta if part)}_")
        text = "\n".join(lines) + "\n"

        def write() -> Path:
            memory_dir.mkdir(parents=True, exist_ok=True)
            path = memory_dir / "memories.md"
            path.write_text(text, encoding="utf-8")
            return path

        return await asyncio.to_thread(write)
