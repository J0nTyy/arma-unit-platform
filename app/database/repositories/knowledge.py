"""Data access for the knowledge document index."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.knowledge import KnowledgeDocument


class KnowledgeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self) -> list[KnowledgeDocument]:
        result = await self._session.execute(
            select(KnowledgeDocument).order_by(KnowledgeDocument.slug)
        )
        return list(result.scalars())

    async def get_by_slug(self, slug: str) -> KnowledgeDocument | None:
        result = await self._session.execute(
            select(KnowledgeDocument).where(KnowledgeDocument.slug == slug)
        )
        return result.scalar_one_or_none()

    async def upsert(self, values: dict[str, Any]) -> KnowledgeDocument:
        document = await self.get_by_slug(values["slug"])
        if document is None:
            document = KnowledgeDocument(**values)
            self._session.add(document)
        else:
            for key, value in values.items():
                setattr(document, key, value)
        await self._session.flush()
        return document

    async def delete_not_in(self, slugs: list[str]) -> int:
        statement = delete(KnowledgeDocument)
        if slugs:
            statement = statement.where(KnowledgeDocument.slug.not_in(slugs))
        result = await self._session.execute(statement)
        return result.rowcount or 0
