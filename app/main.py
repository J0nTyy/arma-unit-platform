"""Application entrypoint.

Runs the Discord bot and the HTTP API in one process for now. Both are
started as independent asyncio tasks against shared infrastructure (settings,
database), so splitting them into separate processes later is a deployment
change, not a code rewrite.
"""

from __future__ import annotations

import asyncio
import logging
import sys

import uvicorn

from app import __version__
from app.api.app import create_app
from app.bot.bot import UnitBot
from app.config import Settings, get_settings
from app.database import Database
from app.errors import ConfigurationError
from app.logging_config import setup_logging

log = logging.getLogger(__name__)


async def _run(settings: Settings) -> bool:
    """Run the application; returns True if a task crashed (dirty exit)."""
    database = Database(settings.database_url)
    if await database.ping():
        log.info("Database connection OK")
    else:
        log.warning(
            "Database is unreachable at startup — check DATABASE_URL. "
            "The bot will still start; /status will report the outage."
        )

    bot = UnitBot(settings, database)
    tasks: list[asyncio.Task[None]] = []
    api_server: uvicorn.Server | None = None
    failed = False
    try:
        tasks.append(
            asyncio.create_task(
                bot.start(settings.discord_token.get_secret_value()), name="discord-bot"
            )
        )
        if settings.api_enabled:
            api_config = uvicorn.Config(
                create_app(),
                host=settings.api_host,
                port=settings.api_port,
                log_config=None,  # inherit our logging setup
            )
            api_server = uvicorn.Server(api_config)
            tasks.append(asyncio.create_task(api_server.serve(), name="api"))
            log.info("API server starting on http://%s:%d", settings.api_host, settings.api_port)

        # If either task exits (crash or clean stop), shut the whole app down.
        done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if task.exception() is not None:
                failed = True
                log.error("Task %r exited with an error", task.get_name(), exc_info=task.exception())
            else:
                log.info("Task %r exited", task.get_name())
        return failed
    finally:
        log.info("Shutting down")
        if api_server is not None:
            api_server.should_exit = True
        if not bot.is_closed():
            await bot.close()
        # Give tasks a grace period to exit cleanly before cancelling.
        if tasks:
            _done, pending = await asyncio.wait(tasks, timeout=10)
            for task in pending:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        await database.dispose()
        log.info("Shutdown complete")


def main() -> None:
    try:
        settings = get_settings()
    except ConfigurationError as exc:
        # Logging is not configured yet — print directly and exit non-zero.
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(1)

    setup_logging(settings.log_level, settings.environment)
    log.info(
        "Starting Arma Unit Platform v%s (environment=%s)", __version__, settings.environment
    )
    try:
        if asyncio.run(_run(settings)):
            raise SystemExit(1)
    except KeyboardInterrupt:
        log.info("Received shutdown signal")


if __name__ == "__main__":
    main()
