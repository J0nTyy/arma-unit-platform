"""AI integration boundary — Phase 1 stub.

Design contract for the future AI assistant:

- The AI never gets raw database access. It calls controlled application
  tools exposed by the service layer (get_unit_information, get_lore,
  get_operation, get_player, get_mission, search_missions, get_schedule, ...).
- Tool registration, prompt construction and API calls all live behind this
  client so the rest of the application only sees `ask(...)`.
- Failures are raised as :class:`app.errors.AIIntegrationError`.
"""

from __future__ import annotations

from typing import Any


class AIClient:
    """Interface contract for the future AI assistant."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key

    async def ask(self, prompt: str, *, context: dict[str, Any] | None = None) -> str:
        """Answer a question using unit knowledge via controlled tools."""
        raise NotImplementedError("The AI assistant is planned for a later phase")
