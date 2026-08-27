"""Learn the server's texting style from ordinary chat.

Keeps a small rolling buffer of recent, normal-looking member messages per
guild (in memory only — nothing is persisted) and serves a handful as
anonymous style examples for the assistant's prompt, so it types like the
room instead of like a press release.

Privacy guardrails:
- staff-only channels are never sampled (their content must not bleed into
  answers given elsewhere)
- author names are never stored, only the text
- links, commands, and very short/long messages are skipped
- the buffer is capped and evaporates on restart
"""

from __future__ import annotations

import random
import re
from collections import deque

_MIN_LENGTH = 8
_MAX_LENGTH = 160
_BUFFER_SIZE = 40
_LINK_RE = re.compile(r"https?://", re.IGNORECASE)
_MENTION_RE = re.compile(r"<[@#][!&]?\d+>|<a?:\w+:\d+>")
_LETTERS_RE = re.compile(r"[A-Za-z]")


class StyleSampler:
    def __init__(self) -> None:
        self._buffers: dict[int, deque[str]] = {}

    def consider(
        self,
        guild_id: int,
        content: str,
        *,
        author_is_bot: bool,
        staff_channel: bool,
    ) -> bool:
        """Maybe add one message to the guild's style buffer."""
        if author_is_bot or staff_channel:
            return False
        text = content.strip()
        if not (_MIN_LENGTH <= len(text) <= _MAX_LENGTH):
            return False
        if text.startswith(("/", "!", ".", "$")):
            return False  # commands
        if _LINK_RE.search(text):
            return False
        if len(_LETTERS_RE.findall(_MENTION_RE.sub("", text))) < 3:
            return False  # mention/emoji-only noise
        buffer = self._buffers.setdefault(guild_id, deque(maxlen=_BUFFER_SIZE))
        buffer.append(_MENTION_RE.sub("@", text))
        return True

    def sample(self, guild_id: int, count: int = 6) -> list[str]:
        buffer = self._buffers.get(guild_id)
        if not buffer:
            return []
        return random.sample(list(buffer), k=min(count, len(buffer)))
