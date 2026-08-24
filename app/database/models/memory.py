from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import Base


class BotMemory(Base):
    """One remembered fact in the unit's server memory.

    The assistant saves these itself (via its save_memory tool) when members
    share durable, unit-relevant facts, and retrieves them by keyword when
    answering later questions. Staff can review and delete entries with
    /unit memories. Capped per guild so it grows slowly, not endlessly.
    """

    __tablename__ = "bot_memories"

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    content: Mapped[str] = mapped_column(String(300))
    author_id: Mapped[int] = mapped_column(BigInteger)  # whose words prompted it
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<BotMemory {self.id} guild={self.guild_id} {self.content[:40]!r}>"
