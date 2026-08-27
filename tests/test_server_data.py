"""Server data directories: creation, sanitization, isolation, versioning."""

from pathlib import Path

import yaml

from app.services.server_data import (
    SERVER_DATA_VERSION,
    ServerDataService,
    sanitize_server_name,
)


def make_service(tmp_path: Path, with_templates: bool = True) -> ServerDataService:
    templates = tmp_path / "templates"
    if with_templates:
        templates.mkdir()
        (templates / "README.md").write_text("about this folder", encoding="utf-8")
    return ServerDataService(root=tmp_path / "servers", templates=templates)


def test_sanitize_server_name():
    assert sanitize_server_name("42nd Ridgeway Rangers") == "42nd-Ridgeway-Rangers"
    assert sanitize_server_name("  ~~ étoile / unit ~~ ") == "toile-unit"
    assert sanitize_server_name("💀💀💀") == "server"  # nothing safe remains
    assert len(sanitize_server_name("x" * 300)) <= 40
    assert "/" not in sanitize_server_name("a/b\\c:d")


def test_ensure_creates_isolated_directories(tmp_path):
    service = make_service(tmp_path)
    context_a = service.ensure(111, "Alpha Unit")
    context_b = service.ensure(222, "Bravo Unit")

    assert context_a.root.name == "Alpha-Unit_111"
    assert context_b.root.name == "Bravo-Unit_222"
    assert context_a.root != context_b.root
    for context in (context_a, context_b):
        assert context.config_dir.is_dir()
        assert context.memory_dir.is_dir()
        assert context.exports_dir.is_dir()
        assert context.logs_dir.is_dir()
        assert (context.root / "README.md").read_text(encoding="utf-8")  # template copied

    # Lookup is strictly by guild ID — Guild A can never resolve to B's dir.
    assert service.find(111).root == context_a.root
    assert service.find(222).root == context_b.root
    assert service.find(999) is None


def test_marker_records_data_version(tmp_path):
    service = make_service(tmp_path)
    context = service.ensure(111, "Alpha")
    assert context.data_version() == SERVER_DATA_VERSION
    marker = yaml.safe_load(context.marker_file.read_text(encoding="utf-8"))
    assert marker["guild_id"] == 111
    assert marker["guild_name"] == "Alpha"


def test_ensure_never_overwrites_existing_files(tmp_path):
    service = make_service(tmp_path)
    context = service.ensure(111, "Alpha")
    (context.config_dir / "notes.txt").write_text("keep me", encoding="utf-8")
    context.marker_file.write_text("data_version: 1\nguild_id: 111\n", encoding="utf-8")
    (context.root / "README.md").write_text("edited by staff", encoding="utf-8")

    again = service.ensure(111, "Alpha")
    assert again.root == context.root
    assert (context.config_dir / "notes.txt").read_text(encoding="utf-8") == "keep me"
    assert (context.root / "README.md").read_text(encoding="utf-8") == "edited by staff"


def test_guild_rename_does_not_orphan_data(tmp_path):
    service = make_service(tmp_path)
    original = service.ensure(111, "Old Name")
    (original.exports_dir / "x.csv").write_text("data", encoding="utf-8")

    renamed = service.ensure(111, "Completely New Name")
    assert renamed.root == original.root  # matched by _<id> suffix, not name
    assert (renamed.exports_dir / "x.csv").exists()
    # No second directory was created for the same guild.
    directories = [d for d in (tmp_path / "servers").iterdir() if d.is_dir()]
    assert len(directories) == 1


def test_bad_marker_reports_no_version(tmp_path):
    service = make_service(tmp_path, with_templates=False)
    context = service.ensure(111, "Alpha")
    context.marker_file.write_text(":\nnot yaml [", encoding="utf-8")
    assert context.data_version() is None
