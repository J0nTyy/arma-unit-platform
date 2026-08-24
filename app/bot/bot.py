"""The Discord bot.

`UnitBot` wires settings, the database, and services together and loads
command/event extensions. Adding a new command in a future phase means adding
a module to EXTENSIONS — no changes to this class.
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from app.bot.error_handler import handle_app_command_error
from app.bot.views.components import DYNAMIC_ITEMS
from app.config import Settings
from app.database import Database
from app.integrations.ai import AIChatClient
from app.integrations.github import GitHubClient
from app.services import (
    AssistantService,
    GuildService,
    KnowledgeService,
    MissionService,
    OperationService,
    PublicationService,
    StatusService,
)
from app.services.assistant import load_personality
from app.services.assistant_tools import build_default_registry

log = logging.getLogger(__name__)

EXTENSIONS = (
    "app.bot.commands.general",
    "app.bot.commands.missions",
    "app.bot.commands.operations",
    "app.bot.commands.assistant",
    "app.bot.commands.unit",
    "app.bot.events.lifecycle",
    "app.bot.events.scheduler",
)


class UnitBot(commands.Bot):
    def __init__(self, settings: Settings, database: Database) -> None:
        intents = discord.Intents.default()
        super().__init__(
            command_prefix=commands.when_mentioned,  # slash commands only
            intents=intents,
            application_id=settings.discord_application_id,
            help_command=None,
        )
        self.settings = settings
        self.database = database
        # Services shared by all cogs — commands never touch the database directly.
        self.guild_service = GuildService(database)
        self.status_service = StatusService(settings, database)
        self.operation_service = OperationService(database)
        self.publication_service = PublicationService(database)

        # Mission repository integration is optional; /mission commands explain
        # the required setup when it is not configured.
        self.github_client: GitHubClient | None = None
        self.mission_service: MissionService | None = None
        self.knowledge_service: KnowledgeService | None = None
        if settings.missions_repository_configured:
            token = settings.github_token.get_secret_value() if settings.github_token else None
            self.github_client = GitHubClient(
                owner=settings.github_missions_owner,  # type: ignore[arg-type]
                repository=settings.github_missions_repository,  # type: ignore[arg-type]
                branch=settings.github_missions_branch,
                token=token,
            )
            self.mission_service = MissionService(database, self.github_client)
            self.knowledge_service = KnowledgeService(database, self.github_client)
            log.info(
                "Mission repository: %s (branch %s)",
                self.github_client.repository_url, settings.github_missions_branch,
            )
        else:
            log.warning(
                "Mission repository not configured: set GITHUB_MISSIONS_OWNER and "
                "GITHUB_MISSIONS_REPOSITORY to enable /mission commands"
            )

        # AI assistant is optional; /ask explains itself when unconfigured.
        self.ai_client: AIChatClient | None = None
        self.assistant_service: AssistantService | None = None
        if settings.ai_configured:
            self.ai_client = AIChatClient(
                api_key=settings.resolved_ai_key.get_secret_value(),  # type: ignore[union-attr]
                model=settings.resolved_ai_model,
                base_url=settings.resolved_ai_base_url,
                max_output_tokens=settings.ai_max_output_tokens,
            )
            self.assistant_service = AssistantService(
                self.ai_client,
                build_default_registry(),
                personality=load_personality(settings.ai_personality_file),
                requests_per_minute=settings.ai_requests_per_minute,
            )
            log.info(
                "Unit assistant enabled: provider=%s model=%s",
                settings.ai_provider, settings.resolved_ai_model,
            )
        else:
            log.warning(
                "Unit assistant disabled: set OPENAI_API_KEY (or GEMINI_API_KEY with "
                "AI_PROVIDER=gemini) to enable /ask"
            )

    async def setup_hook(self) -> None:
        self.tree.error(handle_app_command_error)
        # Persistent buttons (attendance, rosters, mission actions) — state
        # lives in custom_ids, so posts keep working across restarts.
        self.add_dynamic_items(*DYNAMIC_ITEMS)
        for extension in EXTENSIONS:
            await self.load_extension(extension)
            log.info("Loaded extension %s", extension)
        await self._sync_commands()

    async def _sync_commands(self) -> None:
        guild_ids = self.settings.dev_guild_id_list
        if guild_ids:
            for guild_id in guild_ids:
                await self._sync_to_guild(guild_id)
        else:
            synced = await self.tree.sync()
            log.info(
                "Synced %d global command(s) — global sync can take up to an hour "
                "to propagate; set DEV_GUILD_IDS for instant sync while developing",
                len(synced),
            )

    async def _sync_to_guild(self, guild_id: int) -> None:
        guild = discord.Object(id=guild_id)
        self.tree.copy_global_to(guild=guild)
        try:
            synced = await self.tree.sync(guild=guild)
        except discord.Forbidden:
            # Stay online so the problem is visible/diagnosable; commands will
            # register on the next start once the invite is fixed.
            invite_url = (
                "https://discord.com/api/oauth2/authorize"
                f"?client_id={self.settings.discord_application_id}"
                "&scope=bot%20applications.commands&permissions=19456"
            )
            log.error(
                "Discord refused command registration (Missing Access): the bot is "
                "not in guild %s, or was invited without the applications.commands "
                "scope. Re-invite it using %s and restart.",
                guild_id, invite_url,
            )
            return
        log.info("Synced %d command(s) to guild %s (instant)", len(synced), guild_id)

    async def close(self) -> None:
        if self.github_client is not None:
            await self.github_client.aclose()
        if self.ai_client is not None:
            await self.ai_client.aclose()
        await super().close()

    async def on_error(self, event_method: str, /, *args: object, **kwargs: object) -> None:
        log.exception("Unhandled exception in event handler %s", event_method)
