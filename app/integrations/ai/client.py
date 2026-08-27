"""Provider-agnostic AI chat client.

One code path serves every OpenAI-compatible provider: OpenAI itself,
Google's Gemini (via its OpenAI-compatibility endpoint), or anything else
reachable through AI_BASE_URL. Switching providers is configuration, not
code (see AI_PROVIDER / AI_MODEL / *_API_KEY in .env).

Transport layer only: it sends messages + tool schemas and returns the
model's reply. Tool execution, permissions, retrieval and conversation
state all live in the assistant service — the model never touches the
application directly.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import openai

from app.errors import AIIntegrationError

log = logging.getLogger(__name__)

# Called after every successful model turn with (input_tokens, output_tokens)
# so the application can track spend. Must never raise.
UsageHook = Callable[[int | None, int | None], Awaitable[None]]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments_json: str


@dataclass(frozen=True)
class AIResponse:
    content: str | None
    tool_calls: tuple[ToolCall, ...] = ()
    # The assistant message in wire format, for appending to the transcript.
    raw_message: dict[str, Any] = field(default_factory=dict)
    input_tokens: int | None = None
    output_tokens: int | None = None


class AIChatClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        max_output_tokens: int = 700,
        timeout: float = 45.0,
        reasoning_effort: str | None = None,
        usage_hook: UsageHook | None = None,
    ) -> None:
        self.model = model
        self._max_output_tokens = max_output_tokens
        self._usage_hook = usage_hook
        # Caps hidden "thinking" spend on reasoning models (gpt-5 family).
        # None = don't send the parameter (required for providers/models that
        # would reject it).
        self._reasoning_effort = reasoning_effort
        self._client = openai.AsyncOpenAI(
            api_key=api_key, base_url=base_url, timeout=timeout, max_retries=1
        )

    async def aclose(self) -> None:
        await self._client.close()

    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> AIResponse:
        """One model turn. Raises AIIntegrationError with a user-safe message
        on any provider failure — callers never see SDK exceptions."""
        started = time.monotonic()
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_completion_tokens": self._max_output_tokens,
        }
        if self._reasoning_effort:
            kwargs["reasoning_effort"] = self._reasoning_effort
        if tools:
            kwargs["tools"] = tools
        try:
            completion = await self._client.chat.completions.create(**kwargs)
        except openai.RateLimitError as exc:
            log.warning("AI provider rate limit: %s", exc.__class__.__name__)
            raise AIIntegrationError(
                "provider rate limit",
                user_message="The unit assistant is very busy right now — try again in a minute.",
            ) from exc
        except (openai.APITimeoutError, openai.APIConnectionError) as exc:
            log.warning("AI provider unreachable: %s", exc.__class__.__name__)
            raise AIIntegrationError("provider unreachable") from exc
        except openai.APIError as exc:
            log.error("AI provider error: %s", getattr(exc, "message", exc.__class__.__name__))
            raise AIIntegrationError("provider error") from exc

        if not completion.choices:
            raise AIIntegrationError("empty completion")
        message = completion.choices[0].message
        tool_calls = tuple(
            ToolCall(id=call.id, name=call.function.name, arguments_json=call.function.arguments)
            for call in (message.tool_calls or [])
            if call.type == "function"
        )
        usage = completion.usage
        log.info(
            "AI turn: model=%s duration=%.1fs tools=%d tokens_in=%s tokens_out=%s",
            self.model,
            time.monotonic() - started,
            len(tool_calls),
            getattr(usage, "prompt_tokens", None),
            getattr(usage, "completion_tokens", None),
        )
        if self._usage_hook is not None:
            await self._usage_hook(
                getattr(usage, "prompt_tokens", None),
                getattr(usage, "completion_tokens", None),
            )
        return AIResponse(
            content=message.content,
            tool_calls=tool_calls,
            raw_message=message.model_dump(exclude_none=True),
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
        )
