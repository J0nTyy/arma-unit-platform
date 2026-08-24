from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import Base


class MissionIndexEntry(Base):
    """Local index of mission metadata synchronized from GitHub.

    GitHub is the source of truth; this table is a cache that lets Discord
    commands list/search/view missions without hitting the GitHub API. It is
    rebuilt by `/mission sync` and only contains missions whose mission.json
    parsed successfully (invalid-but-parseable missions are stored with
    is_valid=False so they can be flagged).
    """

    __tablename__ = "missions"

    id: Mapped[int] = mapped_column(primary_key=True)
    mission_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))
    map_name: Mapped[str] = mapped_column(String(60))
    mission_type: Mapped[str] = mapped_column(String(50))
    difficulty: Mapped[str] = mapped_column(String(20))
    minimum_players: Mapped[int] = mapped_column(Integer)
    maximum_players: Mapped[int] = mapped_column(Integer)
    estimated_duration_minutes: Mapped[int] = mapped_column(Integer)
    mission_maker: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(500))
    version: Mapped[str] = mapped_column(String(20))
    factions: Mapped[list[str]] = mapped_column(JSON)
    required_mods: Mapped[list[str]] = mapped_column(JSON)
    tags: Mapped[list[str]] = mapped_column(JSON)
    # Repository directory the mission lives in, e.g. "active/OP-001-blackout"
    directory: Mapped[str] = mapped_column(String(255))
    is_valid: Mapped[bool] = mapped_column(Boolean)
    validation_errors: Mapped[list[str]] = mapped_column(JSON)
    validation_warnings: Mapped[list[str]] = mapped_column(JSON)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<MissionIndexEntry {self.mission_id} {self.name!r} status={self.status}>"
