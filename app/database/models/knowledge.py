from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import Base


class KnowledgeDocument(Base):
    """Indexed copy of one knowledge file from the missions repository.

    GitHub remains the source of truth; this table is a disposable cache
    rebuilt by /unit sync, exactly like the mission index.
    """

    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(50))
    tags: Mapped[list[str]] = mapped_column(JSON)
    visibility: Mapped[str] = mapped_column(String(10))
    content: Mapped[str] = mapped_column(Text)
    source_path: Mapped[str] = mapped_column(String(255))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<KnowledgeDocument {self.slug} ({self.visibility})>"
