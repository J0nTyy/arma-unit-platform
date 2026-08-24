"""Mission publication bookkeeping.

Tracks which mission has been published as which Discord message so the bot
can update the same message instead of reposting, and detect duplicates.
Sending/editing the actual Discord messages is interface work and stays in
the bot layer.
"""

from __future__ import annotations

import logging

from sqlalchemy.exc import SQLAlchemyError

from app.database import Database
from app.database.models.operation import MissionPublication
from app.database.repositories.operations import MissionPublicationRepository
from app.errors import DatabaseError

log = logging.getLogger(__name__)


class PublicationService:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def get_publication(self, guild_id: int, mission_id: str) -> MissionPublication | None:
        try:
            async with self._database.session() as session:
                return await MissionPublicationRepository(session).get(guild_id, mission_id)
        except SQLAlchemyError as exc:
            raise DatabaseError("get_publication failed") from exc

    async def list_publications(self, guild_id: int) -> list[MissionPublication]:
        try:
            async with self._database.session() as session:
                return await MissionPublicationRepository(session).list_for_guild(guild_id)
        except SQLAlchemyError as exc:
            raise DatabaseError("list_publications failed") from exc

    async def record_publication(
        self,
        *,
        guild_id: int,
        mission_id: str,
        channel_id: int,
        message_id: int,
        published_by: int,
    ) -> MissionPublication:
        try:
            async with self._database.session() as session, session.begin():
                repository = MissionPublicationRepository(session)
                existing = await repository.get(guild_id, mission_id)
                if existing is not None and existing.channel_id == channel_id:
                    existing.message_id = message_id
                    existing.published_by = published_by
                    await session.flush()
                    await session.refresh(existing)
                    return existing
                publication = await repository.record(
                    {
                        "guild_id": guild_id,
                        "mission_id": mission_id.upper(),
                        "channel_id": channel_id,
                        "message_id": message_id,
                        "published_by": published_by,
                    }
                )
                log.info(
                    "Recorded publication of %s in guild %s channel %s",
                    mission_id, guild_id, channel_id,
                )
                return publication
        except SQLAlchemyError as exc:
            raise DatabaseError("record_publication failed") from exc

    async def forget_publication(self, publication_id: int) -> None:
        """Drop a stale record (e.g. the Discord message was deleted)."""
        try:
            async with self._database.session() as session, session.begin():
                await MissionPublicationRepository(session).remove(publication_id)
        except SQLAlchemyError as exc:
            raise DatabaseError("forget_publication failed") from exc
