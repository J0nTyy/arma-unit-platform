"""Data-driven message variation.

Bot-generated messages that users see often (greetings, confirmations,
reminder nudges) come from YAML variant files instead of strings hardcoded
in command code, so the bot doesn't repeat one canned phrase forever and
staff can re-voice it without touching Python:

    content/messages/*.yaml   shipped defaults (in the bot's voice)
    unit/messages/*.yaml      optional per-unit overrides (same keys win)

File schema — either a plain list, or variants + optional `witty` extras
that are only used when the unit's humour setting allows:

    operation_cancelled_note:
      variants:
        - "Operation cancelled."
      witty:
        - "Operation cancelled. The enemy has been granted a temporary
           reprieve."

Controlled randomness, not chaos: picks avoid repeating the previous
variant for the same key, and anything serious (errors, permission denials)
stays OUT of this system on purpose — those messages are deterministic.
"""

from __future__ import annotations

import logging
import random
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

# Humour levels that unlock the `witty` extras (see PersonalitySettings).
_WITTY_LEVELS = {"medium", "high"}


class MessageCatalog:
    def __init__(
        self,
        base_dir: Path | str = "content/messages",
        override_dir: Path | str | None = None,
        *,
        humour: str = "medium",
    ) -> None:
        self._humour = humour
        self._entries: dict[str, dict[str, list[str]]] = {}
        self._last_pick: dict[str, str] = {}
        self._load(Path(base_dir))
        if override_dir is not None:
            self._load(Path(override_dir))  # same key -> override replaces it

    def _load(self, directory: Path) -> None:
        if not directory.is_dir():
            return
        for file in sorted(directory.glob("*.yaml")):
            try:
                data = yaml.safe_load(file.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError) as exc:
                log.warning("Message file %s skipped: %s", file, exc.__class__.__name__)
                continue
            if not isinstance(data, dict):
                continue
            for key, raw in data.items():
                entry = self._parse_entry(raw)
                if entry is None:
                    log.warning("Message key %r in %s has no usable variants", key, file)
                    continue
                self._entries[str(key)] = entry

    @staticmethod
    def _parse_entry(raw: object) -> dict[str, list[str]] | None:
        if isinstance(raw, list):
            variants = [str(item) for item in raw if str(item).strip()]
            return {"variants": variants, "witty": []} if variants else None
        if isinstance(raw, dict):
            variants = [str(item) for item in raw.get("variants", []) if str(item).strip()]
            witty = [str(item) for item in raw.get("witty", []) if str(item).strip()]
            return {"variants": variants, "witty": witty} if (variants or witty) else None
        return None

    def keys(self) -> set[str]:
        return set(self._entries)

    def variants_for(self, key: str) -> list[str]:
        """The pool pick() chooses from (visible for tests/tuning)."""
        entry = self._entries.get(key)
        if entry is None:
            return []
        pool = list(entry["variants"])
        if self._humour in _WITTY_LEVELS:
            pool += entry["witty"]
        return pool or list(entry["witty"])  # humour off + witty-only entry

    def pick(self, key: str, *, fallback: str | None = None, **format_args: object) -> str:
        """One variant, formatted. Never the same one twice in a row (when
        there's a choice). Unknown key -> fallback, or KeyError without one."""
        pool = self.variants_for(key)
        if not pool:
            if fallback is None:
                raise KeyError(f"no message variants for key {key!r}")
            return fallback.format(**format_args) if format_args else fallback
        candidates = [v for v in pool if v != self._last_pick.get(key)] or pool
        choice = random.choice(candidates)
        self._last_pick[key] = choice
        return choice.format(**format_args) if format_args else choice
