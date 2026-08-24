"""Operational health reporting.

Used by the /status Discord command today; the HTTP API can reuse it later
for a richer health endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass

from app import __version__
from app.config import Settings
from app.database import Database


@dataclass(frozen=True)
class StatusReport:
    version: str
    environment: str
    database_connected: bool


class StatusService:
    def __init__(self, settings: Settings, database: Database) -> None:
        self._settings = settings
        self._database = database

    async def check(self) -> StatusReport:
        return StatusReport(
            version=__version__,
            environment=self._settings.environment,
            database_connected=await self._database.ping(),
        )
