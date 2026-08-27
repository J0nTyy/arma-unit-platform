from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, false, func, true
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import Base

# Channel purposes the bot can be configured with, in display order.
CHANNEL_KINDS = (
    ("attendance_channel_id", "Attendance"),
    ("briefing_channel_id", "Operation brief"),
    ("ask_channel_id", "Ask the unit (AI)"),
    ("operations_channel_id", "Operations"),
    ("missions_channel_id", "Missions"),
    ("announcements_channel_id", "Announcements"),
    ("general_channel_id", "General"),
    ("operation_logs_channel_id", "Operation logs"),
    ("logs_channel_id", "Bot logs"),
    ("recruitment_channel_id", "Recruitment"),
    ("aar_channel_id", "After-action reports"),
    ("staff_channel_id", "Staff"),
)

# Channels ordinary members can't see. Never surfaced to non-staff — a
# mention would render as an "unknown channel" and leak that it exists.
PRIVATE_CHANNEL_KEYS = frozenset(
    {"staff_channel_id", "operation_logs_channel_id", "logs_channel_id"}
)


class GuildConfiguration(Base):
    """Per-Discord-server configuration.

    Lets the bot serve multiple guilds without hardcoding one server.
    Channel/role IDs are Discord snowflakes chosen through /unit setup —
    never typed by hand and never hardcoded.
    """

    __tablename__ = "guild_configurations"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Discord snowflake IDs exceed 32-bit integers
    guild_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    guild_name: Mapped[str] = mapped_column(String(200))

    # General settings
    unit_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # IANA timezone name (e.g. Asia/Kolkata); required before scheduling works
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reminders_enabled: Mapped[bool] = mapped_column(Boolean, server_default=true())

    # Roles (fall back to Discord's Manage Server permission when unset)
    staff_role_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mission_maker_role_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Members holding this role may grant/revoke training certifications.
    trainer_role_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Members holding this role see developer-only data (AI spend, internals).
    # Orthogonal to staff on purpose; unset = server owner only.
    developer_role_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Ambient chatter: occasional in-character messages in the general
    # channel (opt-in — costs AI tokens and personality is a taste thing).
    chatter_enabled: Mapped[bool] = mapped_column(Boolean, server_default=false())

    # Channels
    operations_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    missions_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    announcements_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    logs_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    recruitment_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    aar_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    staff_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Signup posts live here; the latest operation stays visible.
    attendance_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Full briefings (+ images) are posted here, one per operation.
    briefing_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Staff-only archive: finished/cancelled operations get logged here.
    operation_logs_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # The server's general chat — announcements are mirrored here.
    general_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Where @mentioning the bot works as a natural-language question.
    ask_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    configured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<GuildConfiguration guild_id={self.guild_id} name={self.guild_name!r}>"
