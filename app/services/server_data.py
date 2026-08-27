"""Per-guild server data directories.

Every Discord guild the bot serves gets an isolated, clearly identifiable
directory under ``data/servers/<sanitized-name>_<guild-id>/``. The guild ID
is always part of the directory name because Discord server names change and
are not unique; lookups therefore match on the ``_<guild-id>`` suffix, never
on the name.

Nothing outside this module builds server-data filesystem paths. Commands
and services ask for a :class:`ServerDataContext` and use its directories.

The database remains canonical for relational data (players, operations,
attendance, memory). These folders hold what belongs on disk: configuration,
human-readable snapshots/exports (Stage 2), memory snapshots, and logs.
"""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

SERVER_DATA_VERSION = 1
_MARKER_FILE = "server.yaml"
_SUBDIRECTORIES = ("config", "memory", "exports", "logs")
_NAME_LIMIT = 40


def sanitize_server_name(name: str) -> str:
    """Make a Discord guild name safe as a directory name.

    Keeps letters/digits, collapses everything else into single dashes.
    Falls back to "server" when nothing safe remains (e.g. emoji-only names).
    """
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-")
    return cleaned[:_NAME_LIMIT].rstrip("-") or "server"


@dataclass(frozen=True)
class ServerDataContext:
    """Handle to one guild's data directory — the only sanctioned way in."""

    guild_id: int
    root: Path

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def memory_dir(self) -> Path:
        return self.root / "memory"

    @property
    def exports_dir(self) -> Path:
        return self.root / "exports"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def marker_file(self) -> Path:
        return self.root / _MARKER_FILE

    def data_version(self) -> int | None:
        try:
            marker = yaml.safe_load(self.marker_file.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            return None
        if isinstance(marker, dict) and isinstance(marker.get("data_version"), int):
            return marker["data_version"]
        return None


class ServerDataService:
    """Creates and resolves per-guild data directories.

    ``ensure()`` is idempotent and never overwrites existing files, so it is
    safe to call on every startup and on every guild join.
    """

    def __init__(
        self,
        root: Path | str = "data/servers",
        templates: Path | str = "templates/server",
    ) -> None:
        self._root = Path(root)
        self._templates = Path(templates)

    @property
    def root(self) -> Path:
        return self._root

    def find(self, guild_id: int) -> ServerDataContext | None:
        """Resolve an existing directory strictly by guild ID suffix.

        The name half of the directory is decorative — a guild rename does
        not orphan its data.
        """
        if not self._root.is_dir():
            return None
        suffix = f"_{guild_id}"
        for entry in sorted(self._root.iterdir()):
            if entry.is_dir() and entry.name.endswith(suffix):
                return ServerDataContext(guild_id=guild_id, root=entry)
        return None

    def ensure(self, guild_id: int, guild_name: str) -> ServerDataContext:
        """Create (or complete) the guild's directory; never overwrites."""
        context = self.find(guild_id)
        if context is None:
            directory = self._root / f"{sanitize_server_name(guild_name)}_{guild_id}"
            context = ServerDataContext(guild_id=guild_id, root=directory)
            log.info("Creating server data directory %s", directory)
        context.root.mkdir(parents=True, exist_ok=True)
        for name in _SUBDIRECTORIES:
            (context.root / name).mkdir(exist_ok=True)
        if not context.marker_file.exists():
            marker = {
                "data_version": SERVER_DATA_VERSION,
                "guild_id": guild_id,
                "guild_name": guild_name,
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            context.marker_file.write_text(
                yaml.safe_dump(marker, sort_keys=False), encoding="utf-8"
            )
        self._copy_templates(context.root)
        return context

    def _copy_templates(self, destination: Path) -> None:
        """Populate documentation/templates into the server dir, no overwrites."""
        if not self._templates.is_dir():
            return
        for source in sorted(self._templates.rglob("*")):
            if not source.is_file():
                continue
            target = destination / source.relative_to(self._templates)
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
