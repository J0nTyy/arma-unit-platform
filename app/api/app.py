"""HTTP API application factory.

Runs alongside the Discord bot in the same process for now; because it is a
plain ASGI app behind a factory, it can move to its own process/container
later without code changes. Future consumers: GitHub webhooks, Arma server
telemetry, a web dashboard.
"""

from __future__ import annotations

from fastapi import FastAPI

from app import __version__
from app.api.routes.health import router as health_router


def create_app() -> FastAPI:
    api = FastAPI(title="Arma Unit Platform API", version=__version__)
    api.include_router(health_router)
    return api
