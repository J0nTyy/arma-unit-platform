"""Claude (Anthropic) chat client.

Anthropic's API is not OpenAI-compatible — the system prompt, tool schemas,
tool calls and tool results all have different wire shapes — so Claude gets
its own client built on the official `anthropic` SDK instead of the shared
OpenAI-compatible path in `client.py`.

The rest of the application never notices the difference: this class speaks
the same interface as AIChatClient (`chat(messages, tools) -> AIResponse`)
and consumes/produces the same OpenAI-style message dicts, so the assistant
service keeps a single transcript format regardless of provider. Translation
to and from Anthropic's format happens entirely inside this module.

Extended thinking is deliberately not enabled: replies are capped at a few
hundred tokens (AI_MAX_OUTPUT_TOKENS) and thinking output would count
against that cap, and keeping the transcript provider-neutral requires no
thinking blocks (Anthropic requires those to be echoed back verbatim).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import anthropic

from app.errors import AIIntegrationError
from app.integrations.ai.client import AIResponse, ToolCall, UsageHook

log = logging.getLogger(__name__)


def convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """OpenAI function specs -> Anthropic tool definitions."""
    return [
        {
            "name": tool["function"]["name"],
            "description": tool["function"]["description"],
            "input_schema": tool["function"]["parameters"],
        }
        for tool in tools
        if tool.get("type") == "function"
    ]


def convert_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """OpenAI-style transcript -> (system text, Anthropic messages).

    - "system" messages move to the top-level system parameter.
    - assistant tool_calls become tool_use content blocks.
    - consecutive "tool" results merge into ONE user message of tool_result
      blocks — Anthropic requires all results of a turn to arrive together.
    """
    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role == "system":
            system_parts.append(str(message.get("content") or ""))
        elif role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": message["tool_call_id"],
                "content": str(message.get("content") or ""),
            }
            previous = converted[-1] if converted else None
            if previous and previous["role"] == "user" and isinstance(previous["content"], list):
                previous["content"].append(block)
            else:
                converted.append({"role": "user", "content": [block]})
        elif role == "assistant" and message.get("tool_calls"):
            blocks: list[dict[str, Any]] = []
            if message.get("content"):
                blocks.append({"type": "text", "text": str(message["content"])})
            for call in message["tool_calls"]:
                function = call["function"]
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
                except (TypeError, ValueError):
                    arguments = {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call["id"],
                        "name": function["name"],
                        "input": arguments,
                    }
                )
            converted.append({"role": "assistant", "content": blocks})
        else:
            converted.append({"role": role, "content": str(message.get("content") or "")})
    return "\n\n".join(part for part in system_parts if part), converted


class ClaudeChatClient:
    """Same interface as AIChatClient, backed by the official Anthropic SDK."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        max_output_tokens: int = 700,
        timeout: float = 45.0,
        usage_hook: UsageHook | None = None,
    ) -> None:
        self.model = model
        self._max_output_tokens = max_output_tokens
        self._usage_hook = usage_hook
        self._client = anthropic.AsyncAnthropic(
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
        system, converted = convert_messages(messages)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self._max_output_tokens,
            "messages": converted,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = convert_tools(tools)
        try:
            response = await self._client.messages.create(**kwargs)
        except anthropic.RateLimitError as exc:
            log.warning("AI provider rate limit: %s", exc.__class__.__name__)
            raise AIIntegrationError(
                "provider rate limit",
                user_message="The unit assistant is very busy right now — try again in a minute.",
            ) from exc
        except (anthropic.APITimeoutError, anthropic.APIConnectionError) as exc:
            log.warning("AI provider unreachable: %s", exc.__class__.__name__)
            raise AIIntegrationError("provider unreachable") from exc
        except anthropic.APIError as exc:
            log.error("AI provider error: %s", getattr(exc, "message", exc.__class__.__name__))
            raise AIIntegrationError("provider error") from exc

        # Claude runs safety classifiers; a decline is a normal 200 response.
        if response.stop_reason == "refusal":
            log.warning("Claude declined the request (stop_reason=refusal)")
            raise AIIntegrationError(
                "model refusal",
                user_message="The assistant can't help with that request.",
            )

        content_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        raw_tool_calls: list[dict[str, Any]] = []
        for block in response.content:
            if block.type == "text":
                content_parts.append(block.text)
            elif block.type == "tool_use":
                arguments_json = json.dumps(block.input or {})
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments_json=arguments_json)
                )
                raw_tool_calls.append(
                    {
                        "id": block.id,
                        "type": "function",
                        "function": {"name": block.name, "arguments": arguments_json},
                    }
                )
        content = "\n".join(content_parts).strip() or None

        # raw_message stays in OpenAI shape so the transcript format is
        # uniform across providers; convert_messages() rebuilds the
        # tool_use blocks losslessly on the next round.
        raw_message: dict[str, Any] = {"role": "assistant"}
        if content:
            raw_message["content"] = content
        if raw_tool_calls:
            raw_message["tool_calls"] = raw_tool_calls

        usage = response.usage
        log.info(
            "AI turn: model=%s duration=%.1fs tools=%d tokens_in=%s tokens_out=%s",
            self.model,
            time.monotonic() - started,
            len(tool_calls),
            getattr(usage, "input_tokens", None),
            getattr(usage, "output_tokens", None),
        )
        if self._usage_hook is not None:
            await self._usage_hook(
                getattr(usage, "input_tokens", None),
                getattr(usage, "output_tokens", None),
            )
        return AIResponse(
            content=content,
            tool_calls=tuple(tool_calls),
            raw_message=raw_message,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        )
