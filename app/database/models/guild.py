from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import Base


class GuildConfiguration(Base):
    """Per-Discord-server configuration.

    Lets the bot serve multiple guilds without hardcoding one server. Future
    phases will extend this (staff role IDs, announcement channels, ...).
    """

    __tablename__ = "guild_configurations"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Discord snowflake IDs exceed 32-bit integers
    guild_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    guild_name: Mapped[str] = mapped_column(String(200))
    configured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<GuildConfiguration guild_id={self.guild_id} name={self.guild_name!r}>"
