"""GitHub REST API client for the missions repository.

Transport layer only: fetches files and directory trees, translates HTTP
failures into the application's error types. It knows nothing about what a
"mission" is — that logic lives in the mission service and domain layer.

Works without a token on public repositories (rate-limited to 60 requests/h);
set GITHUB_TOKEN (fine-grained PAT with read access to repository contents)
for private repositories and higher rate limits.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.errors import GitHubFileNotFoundError, GitHubUnavailableError

log = logging.getLogger(__name__)

_API_VERSION = "2022-11-28"


@dataclass(frozen=True)
class TreeEntry:
    """One path in the repository tree."""

    path: str
    type: str  # "blob" (file) or "tree" (directory)
    size: int


class GitHubClient:
    def __init__(
        self,
        owner: str,
        repository: str,
        branch: str = "main",
        *,
        token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._owner = owner
        self._repository = repository
        self._branch = branch
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": _API_VERSION,
            "User-Agent": "arma-unit-platform",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._http = httpx.AsyncClient(
            base_url="https://api.github.com",
            headers=headers,
            timeout=timeout,
            transport=transport,
        )

    @property
    def repository_url(self) -> str:
        return f"https://github.com/{self._owner}/{self._repository}"

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _get(self, path: str, params: dict[str, str] | None = None) -> Any:
        try:
            response = await self._http.get(path, params=params)
        except httpx.HTTPError as exc:
            log.warning("GitHub request failed: GET %s (%s)", path, exc)
            raise GitHubUnavailableError(f"GET {path} failed: {exc}") from exc

        if response.status_code == 404:
            raise GitHubFileNotFoundError(f"GET {path} -> 404")
        if response.status_code in (401, 403):
            log.error(
                "GitHub denied access (HTTP %d) for GET %s — check GITHUB_TOKEN "
                "permissions or rate limits",
                response.status_code, path,
            )
            raise GitHubUnavailableError(f"GET {path} -> {response.status_code}")
        if response.status_code >= 400:
            log.error("GitHub returned HTTP %d for GET %s", response.status_code, path)
            raise GitHubUnavailableError(f"GET {path} -> {response.status_code}")
        return response.json()

    async def get_file(self, path: str) -> str:
        """Fetch a file's text content from the configured branch."""
        data = await self._get(
            f"/repos/{self._owner}/{self._repository}/contents/{path}",
            params={"ref": self._branch},
        )
        if isinstance(data, list):
            raise GitHubFileNotFoundError(f"{path} is a directory, not a file")
        if data.get("encoding") != "base64" or "content" not in data:
            # Happens for files > 1 MB; mission files should never be that large.
            raise GitHubUnavailableError(f"{path}: unsupported content encoding")
        return base64.b64decode(data["content"]).decode("utf-8")

    async def get_binary_file(self, path: str) -> bytes:
        """Fetch a file's raw bytes (images, PDFs, ...) from the branch."""
        url = f"/repos/{self._owner}/{self._repository}/contents/{path}"
        try:
            response = await self._http.get(
                url,
                params={"ref": self._branch},
                headers={"Accept": "application/vnd.github.raw+json"},
            )
        except httpx.HTTPError as exc:
            log.warning("GitHub request failed: GET %s (%s)", url, exc)
            raise GitHubUnavailableError(f"GET {path} failed: {exc}") from exc
        if response.status_code == 404:
            raise GitHubFileNotFoundError(f"GET {path} -> 404")
        if response.status_code >= 400:
            log.error("GitHub returned HTTP %d for GET %s", response.status_code, url)
            raise GitHubUnavailableError(f"GET {path} -> {response.status_code}")
        return response.content

    async def get_tree(self) -> list[TreeEntry]:
        """List every path in the repository (single API call)."""
        data = await self._get(
            f"/repos/{self._owner}/{self._repository}/git/trees/{self._branch}",
            params={"recursive": "1"},
        )
        if data.get("truncated"):
            log.warning(
                "GitHub tree listing was truncated — the missions repository is "
                "unusually large; some missions may not be discovered"
            )
        return [
            TreeEntry(path=entry["path"], type=entry["type"], size=entry.get("size", 0))
            for entry in data.get("tree", [])
        ]
