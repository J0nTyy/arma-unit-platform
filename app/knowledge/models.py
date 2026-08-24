"""Knowledge document format and validation.

Documents are Markdown files in the missions repository's ``knowledge/``
folder, with a small frontmatter block staff can edit without tooling:

    ---
    title: Getting Started
    visibility: member
    tags: onboarding, new-players
    ---

    # Getting Started
    ...

The parser is deliberately forgiving in format (plain key: value lines, no
YAML dependency) but strict in validation: bad visibility values or missing
titles are reported at sync time, and a malformed file is skipped — never
allowed to crash the bot.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field


class KnowledgeVisibility(str, enum.Enum):
    """Who may see a document. The application enforces this — never the AI.

    public — anyone (basic unit info, recruitment, public lore)
    member — unit members (SOPs, onboarding internals, mod setup)
    staff  — staff only (admin procedures, private operational docs)
    """

    PUBLIC = "public"
    MEMBER = "member"
    STAFF = "staff"


# Which visibilities each requester tier may read, lowest to highest.
VISIBLE_TO = {
    KnowledgeVisibility.PUBLIC: (KnowledgeVisibility.PUBLIC,),
    KnowledgeVisibility.MEMBER: (KnowledgeVisibility.PUBLIC, KnowledgeVisibility.MEMBER),
    KnowledgeVisibility.STAFF: (
        KnowledgeVisibility.PUBLIC,
        KnowledgeVisibility.MEMBER,
        KnowledgeVisibility.STAFF,
    ),
}

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(?P<meta>.*?)\n---\s*\n?", re.DOTALL)
_KNOWN_KEYS = {"title", "visibility", "tags"}


@dataclass
class ParsedDocument:
    slug: str          # path under knowledge/, no extension: "onboarding/mods"
    category: str      # first folder ("general" for root files)
    title: str = ""
    visibility: KnowledgeVisibility = KnowledgeVisibility.MEMBER
    tags: list[str] = field(default_factory=list)
    body: str = ""
    errors: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors


def parse_knowledge_document(path: str, content: str) -> ParsedDocument:
    """Parse and validate one knowledge file. Never raises."""
    slug = path.removeprefix("knowledge/").removesuffix(".md")
    category = slug.split("/", 1)[0] if "/" in slug else "general"
    document = ParsedDocument(slug=slug, category=category)

    match = _FRONTMATTER_RE.match(content)
    if match is None:
        document.errors.append(
            "missing frontmatter block (start the file with --- title/visibility/tags ---)"
        )
        document.body = content.strip()
        return document

    document.body = content[match.end():].strip()
    for line_number, raw_line in enumerate(match.group("meta").splitlines(), start=2):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            document.errors.append(f"line {line_number}: expected 'key: value', got {line!r}")
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key not in _KNOWN_KEYS:
            document.errors.append(f"unknown frontmatter key '{key}'")
            continue
        if key == "title":
            document.title = value
        elif key == "visibility":
            try:
                document.visibility = KnowledgeVisibility(value.lower())
            except ValueError:
                document.errors.append(
                    f"invalid visibility '{value}' (use public, member or staff)"
                )
        elif key == "tags":
            cleaned = value.strip("[]")
            document.tags = [
                tag.strip().lower() for tag in cleaned.split(",") if tag.strip()
            ]

    if not document.title:
        document.errors.append("missing 'title' in frontmatter")
    if not document.body:
        document.errors.append("document has no content below the frontmatter")
    return document
