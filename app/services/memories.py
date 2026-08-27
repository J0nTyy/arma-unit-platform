"""The unit's server memory.

The assistant saves short durable facts here (its own save_memory tool
decides when something is worth keeping) and retrieves the most relevant
ones by keyword before answering. Guild-scoped, size-capped, and staff can
review/delete entries via /unit memories.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import SQLAlchemyError

from app.database import Database
from app.database.models.memory import BotMemory
from app.errors import DatabaseError

log = logging.getLogger(__name__)

_MAX_MEMORIES_PER_GUILD = 400
_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
_STOPWORDS = {
    "at", "on", "we", "do", "is", "to", "in", "of", "or", "an", "the", "and",
    "are", "for", "was", "our", "you", "who", "why", "how", "what", "when",
    "where", "does", "usually", "about", "with", "that", "this", "it",
}


def _tokens(text: str) -> set[str]:
    # Light plural folding ("ops" matches "op") keeps recall forgiving.
    return {
        token.rstrip("s") or token
        for token in _TOKEN_RE.findall(text.lower())
        if token not in _STOPWORDS
    }


class MemoryService:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def remember(
        self,
        guild_id: int,
        content: str,
        author_id: int,
        *,
        visibility: str = "unit",
        days_valid: int | None = None,
    ) -> BotMemory:
        content = " ".join(content.split())[:300]
        expires_at = (
            datetime.now(timezone.utc) + timedelta(days=days_valid)
            if days_valid and days_valid > 0
            else None
        )
        try:
            async with self._database.session() as session, session.begin():
                memory = BotMemory(
                    guild_id=guild_id, content=content, author_id=author_id,
                    visibility=visibility, expires_at=expires_at,
                )
                session.add(memory)
                await session.flush()
                # Expired entries are pruned whenever something new is learned.
                await session.execute(
                    delete(BotMemory).where(
                        BotMemory.guild_id == guild_id,
                        BotMemory.expires_at.is_not(None),
                        BotMemory.expires_at < datetime.now(timezone.utc),
                    )
                )
                # Cap per guild: oldest memories fade first, like a real NCO.
                count = await session.execute(
                    select(func.count()).select_from(BotMemory).where(
                        BotMemory.guild_id == guild_id
                    )
                )
                overflow = int(count.scalar_one()) - _MAX_MEMORIES_PER_GUILD
                if overflow > 0:
                    oldest = await session.execute(
                        select(BotMemory.id)
                        .where(BotMemory.guild_id == guild_id)
                        .order_by(BotMemory.created_at)
                        .limit(overflow)
                    )
                    await session.execute(
                        delete(BotMemory).where(BotMemory.id.in_([r[0] for r in oldest.all()]))
                    )
                await session.refresh(memory)
                log.info("Memory saved for guild %s (id=%d)", guild_id, memory.id)
                return memory
        except SQLAlchemyError as exc:
            raise DatabaseError("remember failed") from exc

    async def recall(
        self, guild_id: int, query: str, limit: int = 5, *, include_staff: bool = False
    ) -> list[BotMemory]:
        """Keyword-overlap retrieval — same philosophy as knowledge search.

        Expired memories are never recalled; staff-visibility memories are
        only recalled when the requester is staff (enforced here, in
        application code — never left to the AI prompt).
        """
        terms = _tokens(query)
        if not terms:
            return []
        now = datetime.now(timezone.utc)
        conditions = [
            BotMemory.guild_id == guild_id,
            or_(BotMemory.expires_at.is_(None), BotMemory.expires_at >= now),
        ]
        if not include_staff:
            conditions.append(BotMemory.visibility == "unit")
        try:
            async with self._database.session() as session:
                result = await session.execute(select(BotMemory).where(*conditions))
                memories = list(result.scalars())
        except SQLAlchemyError as exc:
            raise DatabaseError("recall failed") from exc
        scored = [
            (len(terms & _tokens(memory.content)), memory) for memory in memories
        ]
        scored = [(score, memory) for score, memory in scored if score > 0]
        scored.sort(key=lambda pair: (pair[0], pair[1].created_at), reverse=True)
        return [memory for _, memory in scored[:limit]]

    async def list_recent(self, guild_id: int, limit: int = 15) -> list[BotMemory]:
        try:
            async with self._database.session() as session:
                result = await session.execute(
                    select(BotMemory)
                    .where(BotMemory.guild_id == guild_id)
                    .order_by(BotMemory.created_at.desc())
                    .limit(limit)
                )
                return list(result.scalars())
        except SQLAlchemyError as exc:
            raise DatabaseError("list_recent failed") from exc

    async def forget(self, guild_id: int, memory_id: int) -> bool:
        try:
            async with self._database.session() as session, session.begin():
                result = await session.execute(
                    delete(BotMemory).where(
                        BotMemory.id == memory_id, BotMemory.guild_id == guild_id
                    )
                )
                return bool(result.rowcount)
        except SQLAlchemyError as exc:
            raise DatabaseError("forget failed") from exc

    async def count(self, guild_id: int) -> int:
        try:
            async with self._database.session() as session:
                result = await session.execute(
                    select(func.count()).select_from(BotMemory).where(
                        BotMemory.guild_id == guild_id
                    )
                )
                return int(result.scalar_one())
        except SQLAlchemyError as exc:
            raise DatabaseError("memory count failed") from exc
