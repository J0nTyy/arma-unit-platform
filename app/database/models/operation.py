from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base


class OperationStatus(str, enum.Enum):
    """Operation lifecycle.

    draft      — being assembled; not visible to members.
    scheduled  — created with a date/time but not yet posted for signups.
    open       — posted to the operations channel; attendance is open.
    locked     — signups closed by staff; post stays visible.
    active     — the operation is running (auto-set at start time).
    completed  — finished; kept for history/attendance stats.
    cancelled  — called off; terminal.
    """

    DRAFT = "draft"
    SCHEDULED = "scheduled"
    OPEN = "open"
    LOCKED = "locked"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


# Valid lifecycle transitions, enforced in the service layer.
ALLOWED_TRANSITIONS: dict[OperationStatus, set[OperationStatus]] = {
    OperationStatus.DRAFT: {OperationStatus.SCHEDULED, OperationStatus.CANCELLED},
    OperationStatus.SCHEDULED: {OperationStatus.OPEN, OperationStatus.CANCELLED},
    OperationStatus.OPEN: {
        OperationStatus.LOCKED,
        OperationStatus.ACTIVE,
        OperationStatus.CANCELLED,
    },
    OperationStatus.LOCKED: {
        OperationStatus.OPEN,
        OperationStatus.ACTIVE,
        OperationStatus.CANCELLED,
    },
    OperationStatus.ACTIVE: {OperationStatus.COMPLETED, OperationStatus.CANCELLED},
    OperationStatus.COMPLETED: set(),
    OperationStatus.CANCELLED: set(),
}


class AttendanceStatus(str, enum.Enum):
    ATTENDING = "attending"
    MAYBE = "maybe"
    DECLINED = "declined"
    WAITLIST = "waitlist"


class Operation(Base):
    """A scheduled instance of a mission.

    Mission content is never duplicated here — `mission_id` references the
    mission index (and through it, GitHub). An operation adds only the
    scheduling/attendance state around that content.
    """

    __tablename__ = "operations"

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    mission_id: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(100))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    # IANA zone the operation was scheduled in (frozen at creation)
    timezone: Mapped[str] = mapped_column(String(64))
    server_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Optional capacity. None = no member limit (the unit's default); the
    # waitlist rules only engage when a capacity is set.
    max_players: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=OperationStatus.SCHEDULED.value)
    created_by: Mapped[int] = mapped_column(BigInteger)

    # The signup post in the attendance channel (set when published)
    channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # The briefing messages in the briefing channel (needed for archiving)
    brief_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    brief_message_ids: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)

    # Archiving lifecycle: completed ops are logged immediately; cancelled
    # ones stay visible for 24h first. archived_at marks the move as done.
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Objectives rendered at creation time, so the post can be rebuilt on
    # every attendance click without a GitHub round-trip.
    objectives_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Persistent reminder bookkeeping — survives restarts by design
    reminder_24h_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reminder_1h_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    attendance: Mapped[list["OperationAttendance"]] = relationship(
        back_populates="operation", cascade="all, delete-orphan", lazy="noload"
    )

    def __repr__(self) -> str:
        return f"<Operation {self.id} {self.name!r} {self.status} at={self.scheduled_at}>"


class OperationAttendance(Base):
    """One member's response to one operation."""

    __tablename__ = "operation_attendance"
    __table_args__ = (UniqueConstraint("operation_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    operation_id: Mapped[int] = mapped_column(
        ForeignKey("operations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger)
    # Captured at response time so rosters render without member fetches
    display_name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(10))
    # Set when the member enters the waitlist; ordering key for promotion
    waitlisted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    responded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    operation: Mapped[Operation] = relationship(back_populates="attendance")


class MissionPublication(Base):
    """A mission embed published to a Discord channel.

    Lets the bot update/edit the same message instead of reposting, and
    detect duplicate publications. mission_id is a plain string reference —
    the mission index is rebuilt by sync and must stay independently
    disposable.
    """

    __tablename__ = "mission_publications"
    __table_args__ = (UniqueConstraint("guild_id", "mission_id", "channel_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    mission_id: Mapped[str] = mapped_column(String(20), index=True)
    channel_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(BigInteger)
    published_by: Mapped[int] = mapped_column(BigInteger)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
