"""Data access for the mission index."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.mission import MissionIndexEntry


class MissionIndexRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_mission_id(self, mission_id: str) -> MissionIndexEntry | None:
        result = await self._session.execute(
            select(MissionIndexEntry).where(
                func.upper(MissionIndexEntry.mission_id) == mission_id.strip().upper()
            )
        )
        return result.scalar_one_or_none()

    async def list_filtered(
        self,
        status: str | None = None,
        map_name: str | None = None,
        mission_type: str | None = None,
    ) -> list[MissionIndexEntry]:
        statement = select(MissionIndexEntry).order_by(MissionIndexEntry.mission_id)
        if status:
            statement = statement.where(MissionIndexEntry.status == status.lower())
        if map_name:
            statement = statement.where(
                func.lower(MissionIndexEntry.map_name) == map_name.strip().lower()
            )
        if mission_type:
            statement = statement.where(
                func.lower(MissionIndexEntry.mission_type) == mission_type.strip().lower()
            )
        result = await self._session.execute(statement)
        return list(result.scalars())

    async def list_all(self) -> list[MissionIndexEntry]:
        return await self.list_filtered()

    async def upsert(self, values: dict[str, Any]) -> MissionIndexEntry:
        entry = await self.get_by_mission_id(values["mission_id"])
        if entry is None:
            entry = MissionIndexEntry(**values)
            self._session.add(entry)
        else:
            for key, value in values.items():
                setattr(entry, key, value)
        await self._session.flush()
        return entry

    async def delete_not_in(self, mission_ids: list[str]) -> int:
        """Remove index entries for missions no longer present in the repo."""
        statement = delete(MissionIndexEntry)
        if mission_ids:
            statement = statement.where(MissionIndexEntry.mission_id.not_in(mission_ids))
        result = await self._session.execute(statement)
        return result.rowcount or 0

    async def latest_synced_at(self) -> datetime | None:
        result = await self._session.execute(select(func.max(MissionIndexEntry.synced_at)))
        return result.scalar_one_or_none()
