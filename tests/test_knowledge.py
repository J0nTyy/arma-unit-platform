"""Knowledge parsing, validation, retrieval and sync."""

from types import SimpleNamespace

from app.knowledge import KnowledgeVisibility, parse_knowledge_document, search_documents
from app.services.knowledge import KnowledgeService
from tests.test_mission_service import FakeGitHubClient

VALID = """---
title: Mod Setup
visibility: member
tags: mods, ace, tfar
---

# Mod Setup

## Installing

Subscribe to the preset and load it in the launcher.

## Radio

TFAR handles radio traffic.
"""


def test_parse_valid_document():
    document = parse_knowledge_document("knowledge/onboarding/mods.md", VALID)
    assert document.is_valid, document.errors
    assert document.slug == "onboarding/mods"
    assert document.category == "onboarding"
    assert document.title == "Mod Setup"
    assert document.visibility is KnowledgeVisibility.MEMBER
    assert document.tags == ["mods", "ace", "tfar"]
    assert document.body.startswith("# Mod Setup")


def test_parse_missing_frontmatter():
    document = parse_knowledge_document("knowledge/x.md", "# Just content")
    assert not document.is_valid
    assert any("frontmatter" in error for error in document.errors)


def test_parse_invalid_visibility():
    content = VALID.replace("visibility: member", "visibility: secret")
    document = parse_knowledge_document("knowledge/x.md", content)
    assert any("invalid visibility" in error for error in document.errors)


def test_parse_missing_title():
    content = VALID.replace("title: Mod Setup\n", "")
    document = parse_knowledge_document("knowledge/x.md", content)
    assert any("missing 'title'" in error for error in document.errors)


def test_parse_unknown_key_and_bad_line():
    content = VALID.replace("tags: mods, ace, tfar", "colour: green\njust a line")
    document = parse_knowledge_document("knowledge/x.md", content)
    assert any("unknown frontmatter key" in error for error in document.errors)
    assert any("expected 'key: value'" in error for error in document.errors)


def test_parse_never_raises_on_garbage():
    document = parse_knowledge_document("knowledge/x.md", "\x00\xff not markdown at all")
    assert not document.is_valid  # reported, not raised


def _doc(slug, title, visibility, content, tags=()):
    return SimpleNamespace(
        slug=slug, title=title, category=slug.split("/")[0], tags=list(tags),
        visibility=visibility, content=content,
    )


DOCS = [
    _doc("onboarding/mods", "Mod Setup", "member",
         "## Installing\nSubscribe to the ACE and TFAR preset.", tags=["mods"]),
    _doc("lore/overview", "Unit Lore", "public", "## Who we are\nThe unit story."),
    _doc("sop/staff-procedures", "Staff Procedures", "staff",
         "## Publishing\nUse /mission publish to post missions."),
]


def test_retrieval_finds_relevant_document():
    passages = search_documents(DOCS, "how do I set up mods?", KnowledgeVisibility.MEMBER)
    assert passages and passages[0].slug == "onboarding/mods"


def test_retrieval_filters_staff_docs_from_members():
    passages = search_documents(DOCS, "publishing procedures", KnowledgeVisibility.MEMBER)
    assert all(p.slug != "sop/staff-procedures" for p in passages)
    staff_passages = search_documents(DOCS, "publishing procedures", KnowledgeVisibility.STAFF)
    assert any(p.slug == "sop/staff-procedures" for p in staff_passages)


def test_retrieval_public_tier_sees_only_public():
    passages = search_documents(DOCS, "mods preset unit", KnowledgeVisibility.PUBLIC)
    assert {p.slug for p in passages} <= {"lore/overview"}


def test_retrieval_no_results():
    assert search_documents(DOCS, "zeppelin maintenance", KnowledgeVisibility.STAFF) == []
    assert search_documents(DOCS, "the a of", KnowledgeVisibility.STAFF) == []  # stopwords only


KNOWLEDGE_FILES = {
    "knowledge/unit.md": VALID.replace("Mod Setup", "Unit Overview")
    .replace("visibility: member", "visibility: public"),
    "knowledge/onboarding/mods.md": VALID,
    "knowledge/sop/staff.md": VALID.replace("visibility: member", "visibility: staff")
    .replace("title: Mod Setup", "title: Staff Doc"),
    "knowledge/broken.md": "no frontmatter here",
    "knowledge/README.md": "# not indexed",
}


async def test_knowledge_sync_indexes_and_reports_failures(database):
    service = KnowledgeService(database, FakeGitHubClient(dict(KNOWLEDGE_FILES)))
    result = await service.sync()
    assert result.indexed == 3
    assert len(result.failures) == 1
    assert result.failures[0][0] == "knowledge/broken.md"
    assert await service.document_count() == 3  # README never indexed

    # member search can't see the staff doc; staff can
    member_hits = await service.search("staff doc setup", KnowledgeVisibility.MEMBER)
    assert all(p.slug != "sop/staff" for p in member_hits)
    staff_hits = await service.search("staff doc setup", KnowledgeVisibility.STAFF)
    assert any(p.slug == "sop/staff" for p in staff_hits)


async def test_knowledge_sync_removes_deleted(database):
    github = FakeGitHubClient(dict(KNOWLEDGE_FILES))
    service = KnowledgeService(database, github)
    await service.sync()
    del github.files["knowledge/onboarding/mods.md"]
    result = await service.sync()
    assert result.removed == 1


async def test_get_document_enforces_visibility(database):
    service = KnowledgeService(database, FakeGitHubClient(dict(KNOWLEDGE_FILES)))
    await service.sync()
    assert await service.get_document("sop/staff", KnowledgeVisibility.MEMBER) is None
    assert await service.get_document("sop/staff", KnowledgeVisibility.STAFF) is not None
