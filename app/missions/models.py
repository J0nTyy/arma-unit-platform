"""Mission content schema — the single source of truth for what a valid
mission is.

These pydantic models validate the JSON files in the missions repository
(`mission.json`, `objectives.json`, `slots.json`). The same models are used
by the Discord bot, the sync indexer, and the local CLI validator, and the
JSON Schema files shipped in the missions repository are generated from them
(see tools/export_mission_schema.py) — so there is exactly ONE definition of
"valid".

Design rules:
- `extra="forbid"` everywhere: a typo like "max_players" is an error a
  mission maker can see and fix, not silently ignored data.
- Structured data lives here; long-form prose belongs in brief.md.
"""

from __future__ import annotations

import enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator, model_validator


class MissionStatus(str, enum.Enum):
    """Mission lifecycle.

    draft        — an idea or skeleton; files may be incomplete; not playable.
    development  — actively being built by the mission maker.
    review       — content-complete; awaiting staff review / test session.
    ready        — approved and playable; can be scheduled as an operation.
    archived     — retired from rotation; kept for history (lives in archived/).
    """

    DRAFT = "draft"
    DEVELOPMENT = "development"
    REVIEW = "review"
    READY = "ready"
    ARCHIVED = "archived"


class Difficulty(str, enum.Enum):
    EASY = "easy"
    STANDARD = "standard"
    HARD = "hard"
    VETERAN = "veteran"


class ObjectiveType(str, enum.Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    OPTIONAL = "optional"


def _drop_schema_key(data: Any) -> Any:
    """Allow a "$schema" key in mission files for editor IntelliSense."""
    if isinstance(data, dict):
        data.pop("$schema", None)
    return data


class MissionMetadata(BaseModel):
    """Contents of mission.json."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(
        pattern=r"^[A-Z]{2,6}-\d{2,4}$",
        description="Unit-wide unique mission ID, e.g. OP-001",
    )
    name: str = Field(min_length=3, max_length=100)
    status: MissionStatus
    mission_maker: str = Field(
        min_length=2, max_length=100, description="Discord / unit identifier of the author"
    )
    description: str = Field(
        min_length=10,
        max_length=500,
        description="Short summary. Long-form briefing belongs in brief.md.",
    )
    map: str = Field(min_length=2, max_length=60)
    mission_type: str = Field(min_length=3, max_length=50)
    difficulty: Difficulty
    estimated_duration_minutes: int = Field(ge=10, le=1440)
    factions: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    version: str = Field(
        pattern=r"^\d+\.\d+\.\d+$", description="Semantic version, e.g. 1.0.0"
    )

    _allow_schema_key = model_validator(mode="before")(_drop_schema_key)

    @field_validator("status", "difficulty", mode="before")
    @classmethod
    def _case_insensitive_enum(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("factions")
    @classmethod
    def _no_blank_entries(cls, value: list[str]) -> list[str]:
        cleaned = [entry.strip() for entry in value]
        if any(not entry for entry in cleaned):
            raise ValueError("must not contain empty entries")
        return cleaned

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, value: list[str]) -> list[str]:
        seen: list[str] = []
        for tag in value:
            tag = tag.strip().lower()
            if not tag:
                raise ValueError("must not contain empty entries")
            if tag not in seen:
                seen.append(tag)
        return seen

class Objective(BaseModel):
    """One entry of objectives.json.

    Objective IDs are the stable keys future Arma telemetry will report
    against (OBJ-01 -> completed), so they must be unique per mission.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(pattern=r"^[A-Z][A-Z0-9-]{1,19}$", description="Stable ID, e.g. OBJ-01")
    name: str = Field(min_length=3, max_length=80)
    description: str = Field(min_length=3, max_length=300)
    type: ObjectiveType
    required: bool

    @field_validator("type", mode="before")
    @classmethod
    def _case_insensitive_enum(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().lower()
        return value


class MissionObjectives(RootModel[list[Objective]]):
    """Contents of objectives.json (a JSON array)."""

    @model_validator(mode="after")
    def _sensible_objective_list(self) -> "MissionObjectives":
        if not self.root:
            raise ValueError("must contain at least one objective")
        seen: set[str] = set()
        for objective in self.root:
            key = objective.id.upper()
            if key in seen:
                raise ValueError(f"duplicate objective ID '{objective.id}'")
            seen.add(key)
        return self


class Slot(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    role: str = Field(min_length=2, max_length=60)
    count: int = Field(ge=1, le=100)


class SlotCategory(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=2, max_length=40)
    slots: list[Slot] = Field(min_length=1)


class MissionSlots(BaseModel):
    """Contents of slots.json."""

    model_config = ConfigDict(extra="forbid")

    categories: list[SlotCategory] = Field(min_length=1)

    _allow_schema_key = model_validator(mode="before")(_drop_schema_key)

    @model_validator(mode="after")
    def _unique_category_names(self) -> "MissionSlots":
        seen: set[str] = set()
        for category in self.categories:
            key = category.name.lower()
            if key in seen:
                raise ValueError(f"duplicate slot category '{category.name}'")
            seen.add(key)
        return self

    @property
    def total_player_count(self) -> int:
        return sum(slot.count for category in self.categories for slot in category.slots)
