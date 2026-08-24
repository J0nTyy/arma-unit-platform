"""Mission business logic.

GitHub is the source of truth for mission content; the database holds an
index of mission metadata so Discord commands can list/search/view without
touching the GitHub API. Live content (briefings, validation) is fetched
fresh from GitHub on demand.

    GitHub  --/mission sync-->  index (DB)  -->  list / search / view
    GitHub  ------------------  live fetch  -->  brief / objectives / validate
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError

from app.database import Database
from app.database.models.mission import MissionIndexEntry
from app.database.repositories.missions import MissionIndexRepository
from app.errors import (
    DatabaseError,
    GitHubFileNotFoundError,
    MissionNotFoundError,
    ValidationError,
)
from app.integrations.github import GitHubClient
from app.missions import (
    MissionFiles,
    Objective,
    MissionObjectives,
    ValidationReport,
    validate_mission_files,
)

log = logging.getLogger(__name__)

_MISSION_JSON_RE = re.compile(r"^((?:active|archived)/[^/]+)/mission\.json$")

# Fields a search query is matched against (case-insensitive substring).
_SEARCH_FIELDS = (
    "mission_id",
    "name",
    "description",
    "map_name",
    "mission_type",
    "mission_maker",
)


@dataclass(frozen=True)
class SyncFailure:
    """A mission directory that could not be indexed at all."""

    directory: str
    errors: tuple[str, ...]


@dataclass(frozen=True)
class SyncResult:
    found: int      # mission directories discovered in the repository
    indexed: int    # entries written to the index (valid + invalid)
    valid: int
    invalid: int
    removed: int    # stale index entries deleted
    failures: tuple[SyncFailure, ...]  # directories with unusable mission.json


class MissionService:
    def __init__(self, database: Database, github: GitHubClient) -> None:
        self._database = database
        self._github = github

    @property
    def repository_url(self) -> str:
        return self._github.repository_url

    # --- synchronization ----------------------------------------------------

    async def sync(self) -> SyncResult:
        """Rebuild the mission index from the GitHub repository."""
        tree = await self._github.get_tree()
        directories = sorted(
            {match.group(1) for entry in tree if (match := _MISSION_JSON_RE.match(entry.path))}
        )

        rows: list[dict] = []
        failures: list[SyncFailure] = []
        seen_ids: set[str] = set()
        synced_at = datetime.now(timezone.utc)

        for directory in directories:
            files = await self._fetch_mission_files(directory)
            report = validate_mission_files(files)
            metadata = report.metadata
            if metadata is None:
                failures.append(SyncFailure(directory, tuple(report.errors)))
                continue
            mission_id = metadata.id.upper()
            if mission_id in seen_ids:
                failures.append(
                    SyncFailure(
                        directory,
                        (f"mission.json: duplicate mission ID '{metadata.id}' — "
                         "already used by another directory",),
                    )
                )
                continue
            seen_ids.add(mission_id)
            rows.append(
                {
                    "mission_id": mission_id,
                    "name": metadata.name,
                    "status": metadata.status.value,
                    "map_name": metadata.map,
                    "mission_type": metadata.mission_type,
                    "difficulty": metadata.difficulty.value,
                    "minimum_players": metadata.minimum_players,
                    "maximum_players": metadata.maximum_players,
                    "estimated_duration_minutes": metadata.estimated_duration_minutes,
                    "mission_maker": metadata.mission_maker,
                    "description": metadata.description,
                    "version": metadata.version,
                    "factions": list(metadata.factions),
                    "required_mods": list(metadata.required_mods),
                    "tags": list(metadata.tags),
                    "directory": directory,
                    "is_valid": report.is_valid,
                    "validation_errors": list(report.errors),
                    "validation_warnings": list(report.warnings),
                    "synced_at": synced_at,
                }
            )

        try:
            async with self._database.session() as session:
                async with session.begin():
                    repository = MissionIndexRepository(session)
                    for row in rows:
                        await repository.upsert(row)
                    removed = await repository.delete_not_in([row["mission_id"] for row in rows])
        except SQLAlchemyError as exc:
            log.exception("Failed to write mission index")
            raise DatabaseError("mission index update failed") from exc

        valid = sum(1 for row in rows if row["is_valid"])
        result = SyncResult(
            found=len(directories),
            indexed=len(rows),
            valid=valid,
            invalid=len(rows) - valid,
            removed=removed,
            failures=tuple(failures),
        )
        log.info(
            "Mission sync complete: %d found, %d indexed (%d valid, %d invalid), "
            "%d removed, %d failed",
            result.found, result.indexed, result.valid, result.invalid,
            result.removed, len(result.failures),
        )
        return result

    async def _fetch_mission_files(self, directory: str) -> MissionFiles:
        async def fetch_optional(filename: str) -> str | None:
            try:
                return await self._github.get_file(f"{directory}/{filename}")
            except GitHubFileNotFoundError:
                return None

        return MissionFiles(
            directory=directory,
            mission_json=await fetch_optional("mission.json"),
            brief_md=await fetch_optional("brief.md"),
            objectives_json=await fetch_optional("objectives.json"),
            slots_json=await fetch_optional("slots.json"),
        )

    # --- index reads (no GitHub calls) --------------------------------------

    async def list_missions(
        self,
        status: str | None = None,
        map_name: str | None = None,
        mission_type: str | None = None,
    ) -> list[MissionIndexEntry]:
        try:
            async with self._database.session() as session:
                return await MissionIndexRepository(session).list_filtered(
                    status=status, map_name=map_name, mission_type=mission_type
                )
        except SQLAlchemyError as exc:
            log.exception("Failed to list missions")
            raise DatabaseError("mission listing failed") from exc

    async def search(self, query: str) -> list[MissionIndexEntry]:
        """Substring search across indexed metadata (IDs, names, tags, ...)."""
        needle = query.strip().lower()
        if not needle:
            return []
        entries = await self.list_missions()
        matches = []
        for entry in entries:
            haystacks = [str(getattr(entry, field_name)) for field_name in _SEARCH_FIELDS]
            haystacks.extend(entry.tags)
            if any(needle in value.lower() for value in haystacks):
                matches.append(entry)
        return matches

    async def get_mission(self, mission_id: str) -> MissionIndexEntry | None:
        try:
            async with self._database.session() as session:
                return await MissionIndexRepository(session).get_by_mission_id(mission_id)
        except SQLAlchemyError as exc:
            log.exception("Failed to load mission %s", mission_id)
            raise DatabaseError(f"get_mission({mission_id}) failed") from exc

    async def last_synced_at(self) -> datetime | None:
        try:
            async with self._database.session() as session:
                return await MissionIndexRepository(session).latest_synced_at()
        except SQLAlchemyError as exc:
            log.exception("Failed to read mission index sync time")
            raise DatabaseError("mission index read failed") from exc

    # --- live content (GitHub calls) -----------------------------------------

    async def get_brief(self, mission_id: str) -> str:
        entry = await self._require_mission(mission_id)
        try:
            return await self._github.get_file(f"{entry.directory}/brief.md")
        except GitHubFileNotFoundError as exc:
            raise GitHubFileNotFoundError(
                f"{entry.directory}/brief.md missing",
                user_message=(
                    f"Mission `{entry.mission_id}` has no `brief.md` in the repository. "
                    "Run `/mission validate` to see what else is missing."
                ),
            ) from exc

    async def get_objectives(self, mission_id: str) -> list[Objective]:
        entry = await self._require_mission(mission_id)
        try:
            content = await self._github.get_file(f"{entry.directory}/objectives.json")
        except GitHubFileNotFoundError as exc:
            raise GitHubFileNotFoundError(
                f"{entry.directory}/objectives.json missing",
                user_message=f"Mission `{entry.mission_id}` has no `objectives.json`.",
            ) from exc
        try:
            return MissionObjectives.model_validate_json(content).root
        except Exception as exc:
            raise ValidationError(
                f"objectives.json invalid for {entry.mission_id}",
                user_message=(
                    f"`objectives.json` for `{entry.mission_id}` is invalid — "
                    f"run `/mission validate {entry.mission_id}` for details."
                ),
            ) from exc

    async def validate_mission(self, mission_id: str) -> ValidationReport:
        """Validate a mission against the repository's CURRENT content."""
        entry = await self.get_mission(mission_id)
        directory = entry.directory if entry else await self._find_directory(mission_id)
        files = await self._fetch_mission_files(directory)
        return validate_mission_files(files)

    async def _find_directory(self, mission_id: str) -> str:
        """Locate an un-indexed mission by directory naming convention."""
        needle = mission_id.strip().lower()
        tree = await self._github.get_tree()
        for entry in tree:
            match = _MISSION_JSON_RE.match(entry.path)
            if match:
                directory = match.group(1)
                name = directory.rsplit("/", 1)[-1].lower()
                if name == needle or name.startswith(f"{needle}-"):
                    return directory
        raise MissionNotFoundError(mission_id)

    async def _require_mission(self, mission_id: str) -> MissionIndexEntry:
        entry = await self.get_mission(mission_id)
        if entry is None:
            raise MissionNotFoundError(mission_id)
        return entry
