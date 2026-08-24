"""Knowledge base business logic.

Knowledge lives as Markdown files under ``knowledge/`` in the missions
repository (GitHub = source of truth). Sync parses + validates every file
into the database index; retrieval serves the AI assistant with
visibility-filtered passages. Malformed files are reported, never fatal.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError

from app.database import Database
from app.database.models.knowledge import KnowledgeDocument
from app.database.repositories.knowledge import KnowledgeRepository
from app.errors import DatabaseError, GitHubFileNotFoundError
from app.integrations.github import GitHubClient
from app.knowledge import (
    KnowledgeVisibility,
    Passage,
    parse_knowledge_document,
    search_documents,
)

log = logging.getLogger(__name__)

_KNOWLEDGE_FILE_RE = re.compile(r"^knowledge/.+\.md$")


@dataclass(frozen=True)
class KnowledgeSyncResult:
    found: int
    indexed: int
    removed: int
    failures: tuple[tuple[str, str], ...]  # (path, first error)


class KnowledgeService:
    def __init__(self, database: Database, github: GitHubClient) -> None:
        self._database = database
        self._github = github

    async def sync(self) -> KnowledgeSyncResult:
        """Rebuild the knowledge index from the repository."""
        tree = await self._github.get_tree()
        paths = sorted(
            entry.path
            for entry in tree
            if entry.type == "blob"
            and _KNOWLEDGE_FILE_RE.match(entry.path)
            and not entry.path.endswith("README.md")
        )
        synced_at = datetime.now(timezone.utc)
        rows: list[dict] = []
        failures: list[tuple[str, str]] = []
        for path in paths:
            try:
                content = await self._github.get_file(path)
            except GitHubFileNotFoundError:
                continue
            document = parse_knowledge_document(path, content)
            if not document.is_valid:
                failures.append((path, document.errors[0]))
                continue
            rows.append(
                {
                    "slug": document.slug,
                    "title": document.title,
                    "category": document.category,
                    "tags": document.tags,
                    "visibility": document.visibility.value,
                    "content": document.body,
                    "source_path": path,
                    "synced_at": synced_at,
                }
            )
        try:
            async with self._database.session() as session, session.begin():
                repository = KnowledgeRepository(session)
                for row in rows:
                    await repository.upsert(row)
                removed = await repository.delete_not_in([row["slug"] for row in rows])
        except SQLAlchemyError as exc:
            log.exception("Failed to write knowledge index")
            raise DatabaseError("knowledge index update failed") from exc

        result = KnowledgeSyncResult(
            found=len(paths), indexed=len(rows), removed=removed, failures=tuple(failures)
        )
        log.info(
            "Knowledge sync: %d found, %d indexed, %d removed, %d failed",
            result.found, result.indexed, result.removed, len(result.failures),
        )
        return result

    async def search(
        self, query: str, requester: KnowledgeVisibility, *, limit: int = 4
    ) -> list[Passage]:
        """Visibility-filtered passage retrieval (filtering is done here, in
        application code — the AI never sees documents above the requester)."""
        try:
            async with self._database.session() as session:
                documents = await KnowledgeRepository(session).list_all()
        except SQLAlchemyError as exc:
            raise DatabaseError("knowledge search failed") from exc
        return search_documents(documents, query, requester, limit=limit)

    async def get_document(
        self, slug: str, requester: KnowledgeVisibility
    ) -> KnowledgeDocument | None:
        try:
            async with self._database.session() as session:
                document = await KnowledgeRepository(session).get_by_slug(slug)
        except SQLAlchemyError as exc:
            raise DatabaseError("knowledge lookup failed") from exc
        if document is None:
            return None
        from app.knowledge.models import VISIBLE_TO

        if document.visibility not in {v.value for v in VISIBLE_TO[requester]}:
            return None
        return document

    async def document_count(self) -> int:
        try:
            async with self._database.session() as session:
                return len(await KnowledgeRepository(session).list_all())
        except SQLAlchemyError as exc:
            raise DatabaseError("knowledge count failed") from exc
