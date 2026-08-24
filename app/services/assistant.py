"""The AI unit assistant.

Pipeline (never a raw passthrough to the model):

    question → rate limit → permissions resolved by the app
             → model + controlled tools (bounded loop)
             → grounded answer

Conversation memory is a short, bounded, in-memory window per user — nothing
is persisted, and question/answer text is never logged (only sizes, models,
durations and tool names).
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.bot.permissions import PermissionLevel
from app.errors import AIIntegrationError, RateLimitedError
from app.integrations.ai import AIChatClient
from app.services.assistant_tools import ToolContext, ToolRegistry

log = logging.getLogger(__name__)

_MAX_TOOL_ROUNDS = 4
_MEMORY_TURNS = 3          # remembered exchanges per user
_MEMORY_TTL_SECONDS = 900  # 15 minutes
_QUESTION_CHAR_LIMIT = 1000

_FALLBACK_PERSONALITY = (
    "You are a helpful, concise assistant for an Arma 3 unit's Discord. Answer "
    "only from tool results; if information is unavailable, say so plainly and "
    "never invent unit facts."
)


def load_personality(path: str) -> str:
    """Personality lives in a content file so staff can tune it without
    touching Python. Falls back to a safe built-in if the file is missing."""
    try:
        text = Path(path).read_text(encoding="utf-8").strip()
        if text:
            return text
    except OSError:
        pass
    log.warning("Personality file %r not found — using built-in fallback", path)
    return _FALLBACK_PERSONALITY


class RateLimiter:
    """Per-user sliding one-minute window. In-memory on purpose — the bot is
    a single process, and losing counters on restart is harmless."""

    def __init__(self, per_minute: int) -> None:
        self._per_minute = max(1, per_minute)
        self._hits: dict[int, deque[float]] = {}

    def check(self, user_id: int) -> None:
        now = time.monotonic()
        hits = self._hits.setdefault(user_id, deque())
        while hits and now - hits[0] > 60:
            hits.popleft()
        if len(hits) >= self._per_minute:
            raise RateLimitedError(retry_seconds=int(61 - (now - hits[0])))
        hits.append(now)


@dataclass
class _Conversation:
    messages: deque = field(default_factory=lambda: deque(maxlen=_MEMORY_TURNS * 2))
    last_active: float = field(default_factory=time.monotonic)


class ConversationMemory:
    """Short per-user context window so follow-ups like "what map?" work."""

    def __init__(self) -> None:
        self._conversations: dict[tuple[int, int], _Conversation] = {}

    def get(self, guild_id: int, user_id: int) -> list[dict]:
        conversation = self._conversations.get((guild_id, user_id))
        if conversation is None:
            return []
        if time.monotonic() - conversation.last_active > _MEMORY_TTL_SECONDS:
            del self._conversations[(guild_id, user_id)]
            return []
        return list(conversation.messages)

    def add(self, guild_id: int, user_id: int, question: str, answer: str) -> None:
        conversation = self._conversations.setdefault((guild_id, user_id), _Conversation())
        conversation.messages.append({"role": "user", "content": question[:600]})
        conversation.messages.append({"role": "assistant", "content": answer[:800]})
        conversation.last_active = time.monotonic()
        # opportunistic cleanup so the dict can't grow unbounded
        if len(self._conversations) > 500:
            cutoff = time.monotonic() - _MEMORY_TTL_SECONDS
            for key in [k for k, c in self._conversations.items() if c.last_active < cutoff]:
                del self._conversations[key]


class AssistantService:
    def __init__(
        self,
        client: AIChatClient,
        registry: ToolRegistry,
        *,
        personality: str,
        requests_per_minute: int = 4,
    ) -> None:
        self._client = client
        self._registry = registry
        self._personality = personality
        self._rate_limiter = RateLimiter(requests_per_minute)
        self._memory = ConversationMemory()

    def _system_prompt(self, context: ToolContext, unit_name: str | None, tz: str | None) -> str:
        now = datetime.now(timezone.utc)
        facts = [
            f"Current time: {now:%Y-%m-%d %H:%M} UTC.",
            f"The requester is a unit {'staff member' if context.level >= PermissionLevel.STAFF else 'member'}.",
        ]
        if unit_name:
            facts.append(f"Unit name: {unit_name}.")
        if tz:
            facts.append(f"Unit timezone: {tz}.")
        return self._personality + "\n\n## Current context\n" + "\n".join(facts)

    async def ask(self, context: ToolContext, question: str) -> str:
        question = question.strip()[:_QUESTION_CHAR_LIMIT]
        if not question:
            return "Ask me something about the unit, its missions or operations!"
        self._rate_limiter.check(context.user_id)

        configuration = await context.bot.guild_service.get_configuration(context.guild_id)
        unit_name = configuration.unit_name or configuration.guild_name if configuration else None
        tz = configuration.timezone if configuration else None

        messages: list[dict] = [
            {"role": "system", "content": self._system_prompt(context, unit_name, tz)}
        ]
        messages += self._memory.get(context.guild_id, context.user_id)
        messages.append({"role": "user", "content": question})

        tools = self._registry.specs_for(context.level)
        started = time.monotonic()
        tool_names: list[str] = []

        answer: str | None = None
        for _ in range(_MAX_TOOL_ROUNDS + 1):
            response = await self._client.chat(messages, tools=tools)
            if not response.tool_calls:
                answer = (response.content or "").strip()
                break
            messages.append(response.raw_message)
            for call in response.tool_calls:
                tool_names.append(call.name)
                result = await self._registry.execute(call.name, call.arguments_json, context)
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": result}
                )
        if not answer:
            log.warning("Assistant produced no final answer (tools used: %s)", tool_names)
            raise AIIntegrationError("no final answer from model")

        log.info(
            "Assistant answered: user=%s level=%s duration=%.1fs tools=%s q_len=%d a_len=%d",
            context.user_id, context.level.name,
            time.monotonic() - started, tool_names or "none", len(question), len(answer),
        )
        self._memory.add(context.guild_id, context.user_id, question, answer)
        return answer
