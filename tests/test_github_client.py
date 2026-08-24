import base64
import json

import httpx
import pytest

from app.errors import GitHubFileNotFoundError, GitHubUnavailableError
from app.integrations.github import GitHubClient


def make_client(handler) -> GitHubClient:
    return GitHubClient(
        owner="unit",
        repository="missions",
        branch="main",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )


def file_response(content: str) -> httpx.Response:
    payload = {
        "encoding": "base64",
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
    }
    return httpx.Response(200, json=payload)


async def test_get_file_decodes_content():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/unit/missions/contents/active/OP-001/mission.json"
        assert request.url.params["ref"] == "main"
        assert request.headers["Authorization"] == "Bearer test-token"
        return file_response('{"id": "OP-001"}')

    client = make_client(handler)
    try:
        content = await client.get_file("active/OP-001/mission.json")
        assert json.loads(content) == {"id": "OP-001"}
    finally:
        await client.aclose()


async def test_get_file_missing_raises_not_found():
    client = make_client(lambda request: httpx.Response(404, json={"message": "Not Found"}))
    try:
        with pytest.raises(GitHubFileNotFoundError):
            await client.get_file("active/OP-999/mission.json")
    finally:
        await client.aclose()


async def test_server_error_raises_unavailable():
    client = make_client(lambda request: httpx.Response(502, text="bad gateway"))
    try:
        with pytest.raises(GitHubUnavailableError):
            await client.get_file("active/OP-001/mission.json")
    finally:
        await client.aclose()


async def test_rate_limit_raises_unavailable():
    client = make_client(lambda request: httpx.Response(403, json={"message": "rate limited"}))
    try:
        with pytest.raises(GitHubUnavailableError):
            await client.get_tree()
    finally:
        await client.aclose()


async def test_network_failure_raises_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = make_client(handler)
    try:
        with pytest.raises(GitHubUnavailableError):
            await client.get_file("anything")
    finally:
        await client.aclose()


async def test_get_tree_parses_entries():
    payload = {
        "truncated": False,
        "tree": [
            {"path": "active", "type": "tree"},
            {"path": "active/OP-001-blackout/mission.json", "type": "blob", "size": 512},
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/unit/missions/git/trees/main"
        assert request.url.params["recursive"] == "1"
        return httpx.Response(200, json=payload)

    client = make_client(handler)
    try:
        tree = await client.get_tree()
        assert len(tree) == 2
        assert tree[1].path == "active/OP-001-blackout/mission.json"
        assert tree[1].type == "blob"
        assert tree[1].size == 512
    finally:
        await client.aclose()
