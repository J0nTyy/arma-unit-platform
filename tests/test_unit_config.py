"""Unit configuration: template initialization, preservation, status."""

from pathlib import Path

from app.services.unit_config import PersonalitySettings, UnitConfigService


def test_personality_settings_defaults_and_lenient_parsing():
    assert PersonalitySettings.from_mapping(None) == PersonalitySettings()
    assert PersonalitySettings.from_mapping("nonsense") == PersonalitySettings()

    parsed = PersonalitySettings.from_mapping(
        {"humour": "HIGH", "formality": "formal", "response_length": "long",
         "tactical_flavor": False}
    )
    assert parsed.humour == "high" and parsed.formality == "formal"
    assert parsed.response_length == "long" and parsed.tactical_flavor is False

    # Invalid values fall back to defaults instead of crashing the bot.
    broken = PersonalitySettings.from_mapping({"humour": "sarcastic", "formality": 3})
    assert broken.humour == "medium" and broken.formality == "balanced"


def test_personality_settings_read_from_unit_yaml(tmp_path):
    service = UnitConfigService(root=tmp_path / "unit", templates=tmp_path / "missing")
    assert service.personality_settings() == PersonalitySettings()  # no file yet

    service.config_file.parent.mkdir(parents=True)
    service.config_file.write_text(
        "schema_version: 1\npersonality:\n  humour: none\n", encoding="utf-8"
    )
    assert service.personality_settings().humour == "none"


def make_templates(tmp_path: Path) -> Path:
    templates = tmp_path / "templates"
    (templates / "config").mkdir(parents=True)
    (templates / "personality").mkdir()
    (templates / "lore").mkdir()
    (templates / "config" / "unit.example.yaml").write_text(
        "schema_version: 1\n", encoding="utf-8"
    )
    (templates / "personality" / "personality.example.md").write_text(
        "You are a template persona.", encoding="utf-8"
    )
    (templates / "lore" / "README.md").write_text("how to write lore", encoding="utf-8")
    return templates


def make_service(tmp_path: Path) -> UnitConfigService:
    return UnitConfigService(root=tmp_path / "unit", templates=make_templates(tmp_path))


def test_initialize_copies_templates_and_strips_example(tmp_path):
    service = make_service(tmp_path)
    created = service.initialize()
    assert len(created) == 3
    assert service.config_file.exists()  # unit.yaml, not unit.example.yaml
    assert service.personality_file.read_text(encoding="utf-8") == "You are a template persona."
    assert (service.lore_dir / "README.md").exists()
    assert service.schema_version() == 1


def test_initialize_never_overwrites(tmp_path):
    service = make_service(tmp_path)
    service.initialize()
    service.personality_file.write_text("My custom persona.", encoding="utf-8")
    created = service.initialize()
    assert created == []  # nothing re-created
    assert service.personality_file.read_text(encoding="utf-8") == "My custom persona."


def test_status_uninitialized_then_initialized(tmp_path):
    service = make_service(tmp_path)
    status = service.status()
    assert status.initialized is False
    assert status.schema_version is None

    service.initialize()
    status = service.status()
    assert status.initialized is True
    assert status.schema_version == 1
    assert status.personality_customized is False  # identical to template

    service.personality_file.write_text("My custom persona.", encoding="utf-8")
    (service.lore_dir / "origins.md").write_text("---\n---\nlore", encoding="utf-8")
    (service.lore_dir / "README.md").write_text("never counted", encoding="utf-8")
    status = service.status()
    assert status.personality_customized is True
    assert status.lore_documents == 1  # README not counted


def test_missing_templates_directory_is_not_fatal(tmp_path):
    service = UnitConfigService(root=tmp_path / "unit", templates=tmp_path / "missing")
    assert service.initialize() == []
    assert service.status().initialized is False


def test_repo_templates_initialize_a_working_unit(tmp_path):
    """The real templates/ shipped in the repo must produce a valid unit dir."""
    service = UnitConfigService(root=tmp_path / "unit", templates="templates/unit")
    created = service.initialize()
    assert created  # something was copied
    assert service.config_file.exists()
    assert service.personality_file.exists()
    assert (service.messages_dir / "README.md").exists()
    assert service.schema_version() == 1
    # The shipped template config parses into valid personality settings.
    settings = service.personality_settings()
    assert settings.humour == "medium" and settings.tactical_flavor is True
