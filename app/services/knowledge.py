"""Knowledge base business logic.

Knowledge lives as local Markdown files in the unit configuration area
(``unit/knowledge/`` and ``unit/lore/`` — private to this deployment, the
source of truth). Sync parses + validates every file into the database
index; retrieval serves the AI assistant with visibility-filtered passages.
Malformed files are reported, never fatal.

Paths are indexed relative to the unit root, so slugs look like
``onboarding/mods`` (from ``unit/knowledge/onboarding/mods.md``) and
``lore/origins`` (from ``unit/lore/origins.md``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from app.database import Database
from app.database.models.knowledge import KnowledgeDocument
from app.database.repositories.knowledge import KnowledgeRepository
from app.errors import DatabaseError
from app.knowledge import (
    KnowledgeVisibility,
    Passage,
    parse_knowledge_document,
    search_documents,
)

log = logging.getLogger(__name__)

# Subdirectories of the unit root that hold indexable documents. Lore is
# knowledge too — it just lives in its own folder for humans.
_DOCUMENT_DIRS = ("knowledge", "lore")


@dataclass(frozen=True)
class KnowledgeSyncResult:
    found: int
    indexed: int
    removed: int
    failures: tuple[tuple[str, str], ...]  # (path, first error)


class KnowledgeService:
    def __init__(self, database: Database, unit_root: Path | str = "unit") -> None:
        self._database = database
        self._unit_root = Path(unit_root)

    def _document_paths(self) -> list[Path]:
        paths: list[Path] = []
        for directory in _DOCUMENT_DIRS:
            base = self._unit_root / directory
            if not base.is_dir():
                continue
            paths.extend(
                f for f in base.rglob("*.md") if f.name.lower() != "readme.md"
            )
        return sorted(paths)

    async def sync(self) -> KnowledgeSyncResult:
        """Rebuild the knowledge index from the unit's local documents."""
        files = self._document_paths()
        synced_at = datetime.now(timezone.utc)
        rows: list[dict] = []
        failures: list[tuple[str, str]] = []
        for file in files:
            relative = file.relative_to(self._unit_root).as_posix()
            try:
                content = file.read_text(encoding="utf-8")
            except OSError as exc:
                failures.append((relative, f"unreadable: {exc.__class__.__name__}"))
                continue
            document = parse_knowledge_document(relative, content)
            if not document.is_valid:
                failures.append((relative, document.errors[0]))
                continue
            rows.append(
                {
                    "slug": document.slug,
                    "title": document.title,
                    "category": document.category,
                    "tags": document.tags,
                    "visibility": document.visibility.value,
                    "content": document.body,
                    "source_path": relative,
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
            found=len(files), indexed=len(rows), removed=removed, failures=tuple(failures)
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
