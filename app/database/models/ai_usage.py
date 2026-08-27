from __future__ import annotations

from datetime import date

from sqlalchemy import BigInteger, Date, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import Base


class AIUsageDaily(Base):
    """One row per (day, provider, model): the bot's AI token consumption.

    Written after every AI call so staff can watch spend from Discord
    (/unit usage) without access to the provider's billing dashboard.
    Token counts are exact (reported by the provider per call); costs are
    estimated at display time from a public price table.
    """

    __tablename__ = "ai_usage_daily"
    __table_args__ = (
        UniqueConstraint("day", "provider", "model", name="uq_ai_usage_day_provider_model"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    provider: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(80))
    requests: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0)

    def __repr__(self) -> str:
        return (
            f"<AIUsageDaily {self.day} {self.provider}/{self.model} "
            f"r={self.requests} in={self.input_tokens} out={self.output_tokens}>"
        )
