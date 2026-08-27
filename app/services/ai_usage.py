"""AI credit usage tracking.

The provider dashboards need account access the unit's staff may not have,
so the bot keeps its own daily counters: every AI call reports its exact
token usage (as billed by the provider) into `ai_usage_daily`, and
/unit usage renders the last weeks with an **estimated** cost from the
public price table below. Estimates are advisory — the provider's invoice
is the truth.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.database import Database
from app.database.models.ai_usage import AIUsageDaily
from app.errors import DatabaseError

log = logging.getLogger(__name__)

# Public prices in USD per 1M tokens: model prefix -> (input, output).
# Matched by longest prefix so dated/model-variant names still resolve.
# None = no reliable public price (e.g. free tiers) -> cost shown as n/a.
_PRICES: dict[str, tuple[float, float] | None] = {
    "gpt-5-nano": (0.05, 0.40),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5": (1.25, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus": (5.00, 25.00),
    "gemini-flash-latest": None,  # free tier in this deployment
    "gemini": None,
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Estimated cost from public prices; None when the model is unknown."""
    for prefix in sorted(_PRICES, key=len, reverse=True):
        if model.startswith(prefix):
            prices = _PRICES[prefix]
            if prices is None:
                return None
            input_price, output_price = prices
            return (input_tokens * input_price + output_tokens * output_price) / 1_000_000
    return None


@dataclass(frozen=True)
class UsageSummary:
    days: list[AIUsageDaily]          # newest first, within the window
    total_requests: int
    total_input_tokens: int
    total_output_tokens: int
    estimated_cost_usd: float | None  # None if ANY row has no known price


class AIUsageService:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def record(
        self, provider: str, model: str, input_tokens: int | None, output_tokens: int | None
    ) -> None:
        """Add one AI call to today's counters. Never raises — usage tracking
        must not break the assistant."""
        try:
            async with self._database.session() as session, session.begin():
                today = date.today()
                row = (
                    await session.execute(
                        select(AIUsageDaily).where(
                            AIUsageDaily.day == today,
                            AIUsageDaily.provider == provider,
                            AIUsageDaily.model == model,
                        )
                    )
                ).scalar_one_or_none()
                if row is None:
                    row = AIUsageDaily(
                        day=today, provider=provider, model=model,
                        requests=0, input_tokens=0, output_tokens=0,
                    )
                    session.add(row)
                row.requests += 1
                row.input_tokens += input_tokens or 0
                row.output_tokens += output_tokens or 0
        except SQLAlchemyError:
            log.exception("Could not record AI usage")

    async def summary(self, days: int = 30) -> UsageSummary:
        since = date.today() - timedelta(days=days - 1)
        try:
            async with self._database.session() as session:
                rows = list(
                    (
                        await session.execute(
                            select(AIUsageDaily)
                            .where(AIUsageDaily.day >= since)
                            .order_by(AIUsageDaily.day.desc())
                        )
                    ).scalars()
                )
        except SQLAlchemyError as exc:
            raise DatabaseError("usage summary failed") from exc

        cost_total = 0.0
        cost_known = True
        for row in rows:
            cost = estimate_cost_usd(row.model, row.input_tokens, row.output_tokens)
            if cost is None:
                cost_known = False
            else:
                cost_total += cost
        return UsageSummary(
            days=rows,
            total_requests=sum(r.requests for r in rows),
            total_input_tokens=sum(r.input_tokens for r in rows),
            total_output_tokens=sum(r.output_tokens for r in rows),
            estimated_cost_usd=cost_total if cost_known else None,
        )
