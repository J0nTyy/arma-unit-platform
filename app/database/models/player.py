from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import Base


class MemberStatus(str, enum.Enum):
    """Staff-controlled unit membership state."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    LEAVE = "leave"      # temporary leave of absence
    RETIRED = "retired"


class FinalAttendance(str, enum.Enum):
    """The authoritative post-operation attendance verdict."""

    ATTENDED = "attended"
    ABSENT = "absent"
    EXCUSED = "excused"


# Gameplay role preferences (NOT Discord roles): slug -> display label.
ROLE_PREFERENCES = {
    "infantry": "🪖 Infantry",
    "medic": "🚑 Medic",
    "recon": "👁️ Recon",
    "armor": "🛡️ Armor",
    "aviation": "🚁 Aviation",
    "logistics": "📦 Logistics",
    "engineer": "🔧 Engineer",
    "jtac": "📡 JTAC",
    "marksman": "🎯 Marksman",
    "leadership": "⭐ Leadership",
}

# Qualification/certification catalog. Trainers grant these via /training;
# granting also assigns the matching Discord role (created if missing).
QUALIFICATIONS = {
    "medic": "🚑 Combat Medic",
    "marksman": "🎯 Marksman",
    "jtac": "📡 JTAC",
    "pilot": "🚁 Pilot",
    "eod": "💣 EOD",
    "engineer": "🔧 Engineer",
    "leadership": "⭐ Leadership",
}

# ── CERT REQUIREMENTS — edit these to match unit policy ──────────────────────
# Eligibility conditions checked by /training certs and shown to players.
#   min_attended: finalized operations attended before training is allowed
#   requires:     other certs that must be held first
# These are starting values — tune freely; nothing else needs to change.
CERT_REQUIREMENTS: dict[str, dict] = {
    "medic":      {"min_attended": 2, "requires": ()},
    "marksman":   {"min_attended": 2, "requires": ()},
    "engineer":   {"min_attended": 2, "requires": ()},
    "pilot":      {"min_attended": 4, "requires": ()},
    "jtac":       {"min_attended": 4, "requires": ("marksman",)},
    "eod":        {"min_attended": 3, "requires": ("engineer",)},
    "leadership": {"min_attended": 6, "requires": ()},
}

EXPERIENCE_LEVELS = {
    "new": "New to Arma",
    "some": "Some experience",
    "experienced": "Experienced",
    "veteran": "Veteran",
}


class Player(Base):
    """A unit member's persistent profile.

    Distinct from the Discord account: Discord is the primary identity today
    (one profile per Discord user per guild), with optional Steam identity,
    and room for Arma identity later. Profiles are never deleted when someone
    leaves Discord — `left_at` marks the departure and history stays intact.
    """

    __tablename__ = "players"
    __table_args__ = (UniqueConstraint("guild_id", "discord_user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    discord_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    join_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    onboarding_status: Mapped[str] = mapped_column(String(20), default="incomplete")
    active_status: Mapped[str] = mapped_column(String(10), default=MemberStatus.ACTIVE.value)

    # Self-service preferences (all optional)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    primary_role: Mapped[str | None] = mapped_column(String(30), nullable=True)
    secondary_role: Mapped[str | None] = mapped_column(String(30), nullable=True)
    arma_experience: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bio: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # Optional linked identities (format-validated, never auto-trusted)
    steam_id: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Set when the Discord account leaves the server; cleared on rejoin.
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<Player {self.id} {self.display_name!r} guild={self.guild_id}>"


class AttendanceRecord(Base):
    """The finalized, authoritative attendance verdict for one player at one
    operation. Separate from the signup rows (operation_attendance), which
    are never overwritten — signing up is not the same as showing up."""

    __tablename__ = "attendance_records"
    __table_args__ = (UniqueConstraint("operation_id", "player_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    operation_id: Mapped[int] = mapped_column(
        ForeignKey("operations.id", ondelete="CASCADE"), index=True
    )
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(10))
    finalized_by: Mapped[int] = mapped_column(BigInteger)
    finalized_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AttendanceAudit(Base):
    """Every finalization/correction of an attendance record, forever."""

    __tablename__ = "attendance_audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(
        ForeignKey("attendance_records.id", ondelete="CASCADE"), index=True
    )
    previous_status: Mapped[str | None] = mapped_column(String(10), nullable=True)
    new_status: Mapped[str] = mapped_column(String(10))
    changed_by: Mapped[int] = mapped_column(BigInteger)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PlayerQualification(Base):
    """A staff-granted qualification (training/progression comes later)."""

    __tablename__ = "player_qualifications"
    __table_args__ = (UniqueConstraint("player_id", "qualification"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    qualification: Mapped[str] = mapped_column(String(30))
    granted_by: Mapped[int] = mapped_column(BigInteger)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
