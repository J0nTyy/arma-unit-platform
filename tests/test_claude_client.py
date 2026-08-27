"""Claude client: OpenAI<->Anthropic wire translation and error mapping.

No real API is used — the Anthropic SDK client inside ClaudeChatClient is
replaced with a scripted fake; SDK exception classes are constructed directly
to verify the error mapping.
"""

import json
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from app.errors import AIIntegrationError
from app.integrations.ai.claude import ClaudeChatClient, convert_messages, convert_tools

OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_missions",
            "description": "Search the mission list.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "additionalProperties": False,
            },
        },
    }
]


# --- pure conversion ---------------------------------------------------------


def test_convert_tools_maps_openai_specs():
    (tool,) = convert_tools(OPENAI_TOOLS)
    assert tool["name"] == "search_missions"
    assert tool["description"] == "Search the mission list."
    assert tool["input_schema"]["properties"]["query"]["type"] == "string"
    assert "function" not in tool  # no OpenAI nesting left over


def test_convert_messages_extracts_system_and_groups_tool_results():
    transcript = [
        {"role": "system", "content": "You are Sarge."},
        {"role": "user", "content": "What's next?"},
        {
            "role": "assistant",
            "content": "Checking.",
            "tool_calls": [
                {"id": "call_1", "type": "function",
                 "function": {"name": "get_upcoming_operations", "arguments": "{}"}},
                {"id": "call_2", "type": "function",
                 "function": {"name": "search_missions", "arguments": '{"query": "iron"}'}},
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "OP-002 Saturday"},
        {"role": "tool", "tool_call_id": "call_2", "content": "OP-002 Iron Rain"},
    ]
    system, messages = convert_messages(transcript)

    assert system == "You are Sarge."
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]

    text, first_call, second_call = messages[1]["content"]
    assert text == {"type": "text", "text": "Checking."}
    assert first_call["type"] == "tool_use" and first_call["id"] == "call_1"
    assert second_call["input"] == {"query": "iron"}  # arguments parsed to dict

    # Both tool results land in ONE user message (Anthropic requirement).
    results = messages[2]["content"]
    assert [r["type"] for r in results] == ["tool_result", "tool_result"]
    assert results[0]["tool_use_id"] == "call_1"
    assert results[1]["content"] == "OP-002 Iron Rain"


def test_convert_messages_plain_conversation():
    system, messages = convert_messages(
        [
            {"role": "system", "content": "Persona."},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "user", "content": "map?"},
        ]
    )
    assert system == "Persona."
    assert messages == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "map?"},
    ]


# --- chat() against a scripted SDK -------------------------------------------


class FakeMessagesAPI:
    def __init__(self, result):
        self.result = result
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def make_client(result) -> tuple[ClaudeChatClient, FakeMessagesAPI]:
    client = ClaudeChatClient.__new__(ClaudeChatClient)  # skip real SDK setup
    client.model = "claude-test"
    client._max_output_tokens = 700
    client._usage_hook = None
    api = FakeMessagesAPI(result)
    client._client = SimpleNamespace(messages=api)
    return client, api


def model_response(*blocks, stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=list(blocks),
        usage=SimpleNamespace(input_tokens=42, output_tokens=7),
    )


async def test_chat_sends_anthropic_format_and_parses_text():
    client, api = make_client(model_response(SimpleNamespace(type="text", text="Iron Rain.")))
    response = await client.chat(
        [
            {"role": "system", "content": "Persona."},
            {"role": "user", "content": "Next op?"},
        ],
        tools=OPENAI_TOOLS,
    )
    assert api.kwargs["model"] == "claude-test"
    assert api.kwargs["max_tokens"] == 700
    assert api.kwargs["system"] == "Persona."
    assert api.kwargs["messages"] == [{"role": "user", "content": "Next op?"}]
    assert api.kwargs["tools"][0]["name"] == "search_missions"
    assert response.content == "Iron Rain."
    assert response.tool_calls == ()
    assert response.input_tokens == 42 and response.output_tokens == 7


async def test_chat_tool_calls_round_trip_through_the_transcript():
    client, _ = make_client(
        model_response(
            SimpleNamespace(type="tool_use", id="toolu_1", name="search_missions",
                            input={"query": "iron"}),
            stop_reason="tool_use",
        )
    )
    response = await client.chat([{"role": "user", "content": "Iron Rain?"}])
    (call,) = response.tool_calls
    assert call.name == "search_missions"
    assert json.loads(call.arguments_json) == {"query": "iron"}

    # The raw_message must reconstruct the tool_use block on the next round,
    # exactly as the assistant service replays the transcript.
    transcript = [
        {"role": "user", "content": "Iron Rain?"},
        response.raw_message,
        {"role": "tool", "tool_call_id": call.id, "content": "OP-002 found"},
    ]
    _, messages = convert_messages(transcript)
    (tool_use,) = messages[1]["content"]
    assert tool_use == {"type": "tool_use", "id": "toolu_1",
                        "name": "search_missions", "input": {"query": "iron"}}
    assert messages[2]["content"][0]["tool_use_id"] == "toolu_1"


async def test_refusal_becomes_clean_error():
    client, _ = make_client(model_response(stop_reason="refusal"))
    with pytest.raises(AIIntegrationError) as info:
        await client.chat([{"role": "user", "content": "hi"}])
    assert "can't help" in info.value.user_message


def _http_response(status: int) -> httpx.Response:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return httpx.Response(status, request=request)


async def test_rate_limit_maps_to_busy_message():
    error = anthropic.RateLimitError("429", response=_http_response(429), body=None)
    client, _ = make_client(error)
    with pytest.raises(AIIntegrationError) as info:
        await client.chat([{"role": "user", "content": "hi"}])
    assert "very busy" in info.value.user_message


async def test_connection_error_maps_to_unavailable():
    error = anthropic.APIConnectionError(
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    client, _ = make_client(error)
    with pytest.raises(AIIntegrationError) as info:
        await client.chat([{"role": "user", "content": "hi"}])
    assert "temporarily unavailable" in info.value.user_message


async def test_api_error_maps_to_unavailable():
    error = anthropic.APIStatusError("boom", response=_http_response(500), body=None)
    client, _ = make_client(error)
    with pytest.raises(AIIntegrationError) as info:
        await client.chat([{"role": "user", "content": "hi"}])
    assert "temporarily unavailable" in info.value.user_message
