"""Keyword-based retrieval over the knowledge index.

Deliberately simple for the first version: tokenize the query, score document
sections by term matches (title and tags weigh more than body text), return
the top passages. The function signature is the contract — a future semantic/
vector implementation can replace the internals without touching the AI
service.

Visibility filtering happens BEFORE scoring: documents the requester may not
see are never considered, so they can never leak into an AI prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Protocol

from app.knowledge.models import VISIBLE_TO, KnowledgeVisibility

_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
_SECTION_RE = re.compile(r"^##\s+(?P<heading>.+?)\s*$", re.MULTILINE)
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "do", "does", "how", "what",
    "when", "where", "who", "why", "in", "on", "of", "to", "for", "our", "my",
    "we", "i", "you", "it", "and", "or", "with", "about", "me", "us", "this",
    "that", "can", "need", "there", "be",
}


class DocumentLike(Protocol):
    slug: str
    title: str
    category: str
    tags: list[str]
    visibility: str
    content: str


@dataclass(frozen=True)
class Passage:
    slug: str
    title: str
    category: str
    heading: str | None
    text: str
    score: float


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


def _sections(content: str) -> list[tuple[str | None, str]]:
    sections: list[tuple[str | None, str]] = []
    last_end = 0
    last_heading: str | None = None
    for match in _SECTION_RE.finditer(content):
        chunk = content[last_end:match.start()].strip()
        if chunk:
            sections.append((last_heading, chunk))
        last_heading = match.group("heading")
        last_end = match.end()
    tail = content[last_end:].strip()
    if tail:
        sections.append((last_heading, tail))
    return sections or [(None, content.strip())]


def search_documents(
    documents: Iterable[DocumentLike],
    query: str,
    requester: KnowledgeVisibility,
    *,
    limit: int = 4,
    max_passage_chars: int = 1400,
) -> list[Passage]:
    terms = set(_tokens(query))
    if not terms:
        return []
    allowed = {v.value for v in VISIBLE_TO[requester]}

    passages: list[Passage] = []
    for document in documents:
        if document.visibility not in allowed:
            continue  # permission filter first — never scored, never leaked
        title_tokens = set(_tokens(document.title)) | set(_tokens(document.slug))
        tag_tokens = set(_tokens(" ".join(document.tags)))
        doc_boost = 3.0 * len(terms & title_tokens) + 2.0 * len(terms & tag_tokens)

        for heading, text in _sections(document.content):
            body_tokens = _tokens(text)
            heading_tokens = set(_tokens(heading or ""))
            occurrences = sum(min(body_tokens.count(term), 4) for term in terms)
            score = doc_boost + 2.0 * len(terms & heading_tokens) + float(occurrences)
            if score <= 0:
                continue
            passages.append(
                Passage(
                    slug=document.slug,
                    title=document.title,
                    category=document.category,
                    heading=heading,
                    text=text[:max_passage_chars],
                    score=score,
                )
            )

    passages.sort(key=lambda p: p.score, reverse=True)
    # At most two passages per document so one long doc can't crowd out others.
    selected: list[Passage] = []
    per_doc: dict[str, int] = {}
    for passage in passages:
        if per_doc.get(passage.slug, 0) >= 2:
            continue
        per_doc[passage.slug] = per_doc.get(passage.slug, 0) + 1
        selected.append(passage)
        if len(selected) >= limit:
            break
    return selected
