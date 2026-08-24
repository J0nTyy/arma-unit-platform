"""Database access infrastructure.

Owns the async engine and session factory. Everything above this layer
(repositories, services) receives sessions rather than creating engines.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

log = logging.getLogger(__name__)


class Database:
    def __init__(self, url: str, *, echo: bool = False) -> None:
        self._engine: AsyncEngine = create_async_engine(url, echo=echo, pool_pre_ping=True)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    def session(self) -> AsyncSession:
        """Create a new session. Use as ``async with db.session() as session:``."""
        return self._session_factory()

    async def ping(self) -> bool:
        """Health probe: True if the database answers a trivial query."""
        try:
            async with self._engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            return True
        except Exception:  # health probe must never raise
            log.exception("Database ping failed")
            return False

    async def dispose(self) -> None:
        await self._engine.dispose()
