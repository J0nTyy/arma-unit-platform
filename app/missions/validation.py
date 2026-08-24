"""Mission bundle validation — the ONE validation implementation.

Validates a mission's set of files as pure content (strings), independent of
where they came from. The Discord bot feeds it content fetched from GitHub;
the CLI tool feeds it files read from a local clone. Both produce identical
results.

Errors block a mission from being considered valid; warnings are advice a
mission maker should look at but do not fail validation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from pydantic import ValidationError as PydanticValidationError

from app.missions.models import (
    MissionMetadata,
    MissionObjectives,
    MissionSlots,
    MissionStatus,
    ObjectiveType,
)

REQUIRED_FILES = ("mission.json", "brief.md", "objectives.json", "slots.json")


@dataclass(frozen=True)
class MissionFiles:
    """The content of one mission directory. None means the file is missing."""

    directory: str  # e.g. "active/OP-001-blackout"
    mission_json: str | None = None
    brief_md: str | None = None
    objectives_json: str | None = None
    slots_json: str | None = None


@dataclass
class ValidationReport:
    directory: str
    metadata: MissionMetadata | None = None
    objectives: MissionObjectives | None = None
    slots: MissionSlots | None = None
    passed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors

    @property
    def mission_id(self) -> str | None:
        return self.metadata.id if self.metadata else None


def _format_pydantic_errors(filename: str, exc: PydanticValidationError) -> list[str]:
    messages = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        prefix = f"{filename}: {location}" if location else filename
        messages.append(f"{prefix}: {error['msg']}")
    return messages


def _parse_json_file(
    filename: str, content: str | None, model: type, report: ValidationReport
) -> object | None:
    """Parse and validate one JSON file; records the outcome on the report."""
    if content is None:
        report.errors.append(f"{filename}: file is missing")
        return None
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        report.errors.append(f"{filename}: not valid JSON ({exc.msg}, line {exc.lineno})")
        return None
    try:
        parsed = model.model_validate(data)
    except PydanticValidationError as exc:
        report.errors.extend(_format_pydantic_errors(filename, exc))
        return None
    report.passed.append(filename)
    return parsed


def validate_mission_files(files: MissionFiles) -> ValidationReport:
    report = ValidationReport(directory=files.directory)

    # --- mission.json -------------------------------------------------------
    metadata = _parse_json_file("mission.json", files.mission_json, MissionMetadata, report)
    report.metadata = metadata  # type: ignore[assignment]

    # --- brief.md -----------------------------------------------------------
    if files.brief_md is None:
        report.errors.append("brief.md: file is missing")
    elif not files.brief_md.strip():
        report.errors.append("brief.md: file is empty")
    else:
        report.passed.append("brief.md")
        if len(files.brief_md.strip()) < 100:
            report.warnings.append("brief.md: briefing is very short (< 100 characters)")
        if not files.brief_md.lstrip().startswith("# "):
            report.warnings.append("brief.md: should start with a top-level heading (# Operation Name)")

    # --- objectives.json ----------------------------------------------------
    objectives = _parse_json_file(
        "objectives.json", files.objectives_json, MissionObjectives, report
    )
    report.objectives = objectives  # type: ignore[assignment]
    if objectives is not None and not any(
        o.type is ObjectiveType.PRIMARY for o in objectives.root
    ):
        report.warnings.append("objectives.json: mission has no primary objective")

    # --- slots.json ---------------------------------------------------------
    slots = _parse_json_file("slots.json", files.slots_json, MissionSlots, report)
    report.slots = slots  # type: ignore[assignment]

    # --- cross-file checks --------------------------------------------------
    directory_name = files.directory.rstrip("/").rsplit("/", 1)[-1]
    if metadata is not None:
        if not directory_name.lower().startswith(metadata.id.lower()):
            report.warnings.append(
                f"directory '{directory_name}' should start with the mission ID "
                f"'{metadata.id}' (e.g. {metadata.id}-short-name)"
            )
        in_archived = files.directory.startswith("archived/")
        if in_archived and metadata.status is not MissionStatus.ARCHIVED:
            report.warnings.append(
                f"mission is in archived/ but status is '{metadata.status.value}' "
                "(expected 'archived')"
            )
        if not in_archived and metadata.status is MissionStatus.ARCHIVED and "/" in files.directory:
            report.warnings.append(
                "status is 'archived' but the mission is not in the archived/ directory"
            )

    if metadata is not None and slots is not None:
        total = slots.total_player_count
        if total != metadata.maximum_players:
            report.warnings.append(
                f"slots.json: total slot count ({total}) does not match "
                f"maximum_players ({metadata.maximum_players})"
            )
        if total < metadata.minimum_players:
            report.warnings.append(
                f"slots.json: total slot count ({total}) is below "
                f"minimum_players ({metadata.minimum_players})"
            )

    return report
