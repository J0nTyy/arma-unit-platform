"""Unit-specific configuration: lore, knowledge, personality, unit settings.

Everything that makes this deployment *this unit* lives under ``unit/`` —
private to the deployment and ignored by Git. The repository ships editable
starting points under ``templates/unit/``; on first run they are copied in
(with ``.example`` stripped from filenames) so a fresh install works out of
the box and staff immediately know where to put their own content.

Layout:

    unit/
    ├── config/unit.yaml        unit settings (schema_version, ...)
    ├── lore/                   canonical unit lore (Markdown + frontmatter)
    ├── knowledge/              unit knowledge base (Markdown + frontmatter)
    └── personality/            AI personality + member greeting

Initialization never overwrites existing files, so editing anything under
``unit/`` is always safe.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

UNIT_SCHEMA_VERSION = 1

_HUMOUR_LEVELS = ("none", "low", "medium", "high")
_FORMALITY_LEVELS = ("casual", "balanced", "formal")
_LENGTHS = ("short", "medium", "long")


@dataclass(frozen=True)
class PersonalitySettings:
    """Style knobs from unit.yaml `personality:` — how the bot talks,
    without editing the personality prose itself."""

    humour: str = "medium"          # none | low | medium | high
    formality: str = "balanced"     # casual | balanced | formal
    response_length: str = "short"  # short | medium | long
    tactical_flavor: bool = True    # military seasoning in wording

    @classmethod
    def from_mapping(cls, raw: object) -> "PersonalitySettings":
        """Parse leniently: unknown/invalid values fall back to defaults."""
        if not isinstance(raw, dict):
            return cls()

        def choose(key: str, allowed: tuple[str, ...], default: str) -> str:
            value = str(raw.get(key, default)).strip().lower()
            if value not in allowed:
                log.warning(
                    "unit.yaml personality.%s=%r is not one of %s — using %r",
                    key, raw.get(key), "/".join(allowed), default,
                )
                return default
            return value

        return cls(
            humour=choose("humour", _HUMOUR_LEVELS, cls.humour),
            formality=choose("formality", _FORMALITY_LEVELS, cls.formality),
            response_length=choose("response_length", _LENGTHS, cls.response_length),
            tactical_flavor=bool(raw.get("tactical_flavor", cls.tactical_flavor)),
        )


@dataclass(frozen=True)
class UnitConfigStatus:
    initialized: bool
    schema_version: int | None
    personality_customized: bool  # real personality differs from the template
    lore_documents: int
    knowledge_documents: int


class UnitConfigService:
    def __init__(
        self, root: Path | str = "unit", templates: Path | str = "templates/unit"
    ) -> None:
        self.root = Path(root)
        self._templates = Path(templates)

    # --- well-known paths (nothing else builds unit/ paths) -------------------

    @property
    def config_file(self) -> Path:
        return self.root / "config" / "unit.yaml"

    @property
    def personality_file(self) -> Path:
        return self.root / "personality" / "personality.md"

    @property
    def messages_dir(self) -> Path:
        """Optional per-unit message-variant overrides (unit/messages/*.yaml)."""
        return self.root / "messages"

    @property
    def lore_dir(self) -> Path:
        return self.root / "lore"

    @property
    def knowledge_dir(self) -> Path:
        return self.root / "knowledge"

    def personality_template(self) -> Path:
        return self._templates / "personality" / "personality.example.md"

    # --- first-run initialization ---------------------------------------------

    def initialize(self) -> list[str]:
        """Copy missing files from templates (``.example`` stripped from the
        target name). Existing files are never touched. Returns created paths."""
        created: list[str] = []
        if not self._templates.is_dir():
            log.warning("Unit templates directory %s missing — nothing to initialize",
                        self._templates)
            return created
        for source in sorted(self._templates.rglob("*")):
            if not source.is_file():
                continue
            relative = source.relative_to(self._templates)
            target_name = relative.name.replace(".example", "")
            target = self.root / relative.parent / target_name
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            created.append(str(target))
        if created:
            log.info("Initialized unit configuration from templates: %d file(s)", len(created))
        return created

    # --- inspection -------------------------------------------------------------

    def load_config(self) -> dict:
        """unit/config/unit.yaml as a dict; {} when missing or malformed."""
        try:
            config = yaml.safe_load(self.config_file.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            return {}
        return config if isinstance(config, dict) else {}

    def schema_version(self) -> int | None:
        version = self.load_config().get("schema_version")
        return version if isinstance(version, int) else None

    def personality_settings(self) -> PersonalitySettings:
        return PersonalitySettings.from_mapping(self.load_config().get("personality"))

    def status(self) -> UnitConfigStatus:
        def markdown_count(directory: Path) -> int:
            if not directory.is_dir():
                return 0
            return sum(
                1 for f in directory.rglob("*.md") if f.name.lower() != "readme.md"
            )

        personality_customized = False
        try:
            personality = self.personality_file.read_text(encoding="utf-8").strip()
            template = self.personality_template().read_text(encoding="utf-8").strip()
            personality_customized = bool(personality) and personality != template
        except OSError:
            pass
        return UnitConfigStatus(
            initialized=self.config_file.exists(),
            schema_version=self.schema_version(),
            personality_customized=personality_customized,
            lore_documents=markdown_count(self.lore_dir),
            knowledge_documents=markdown_count(self.knowledge_dir),
        )
