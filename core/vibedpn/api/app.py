"""ASGI application factory: ``/health`` and the provider statistics (Stage 2)."""

from collections.abc import Callable
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from vibedpn import __version__
from vibedpn.config import Config
from vibedpn.engine.myst import MystError, ProviderStats, TequilaClient, provider_stats

StatsSource = Callable[[], ProviderStats]


class Health(BaseModel):
    """Liveness answer used by the container healthcheck."""

    status: Literal["ok"]
    version: str


def _default_stats() -> ProviderStats:
    client = TequilaClient()
    try:
        return provider_stats(client)
    finally:
        client.close()


def create_app(config: Config | None = None, stats_source: StatsSource = _default_stats) -> FastAPI:
    """Build the application. A factory keeps tests free of import-time side effects.

    ``config`` is the box configuration (``None`` before ``vibedpn-core`` loads it, e.g. in
    tests of ``/health``); ``stats_source`` is swapped in tests for a recorded node.
    """
    application = FastAPI(title="VibeDPN core API", version=__version__)

    @application.get("/health", response_model=Health)
    def health() -> Health:
        return Health(status="ok", version=__version__)

    @application.get("/provider/stats", response_model=ProviderStats)
    def stats() -> ProviderStats:
        if config is None or not config.provider.enabled:
            raise HTTPException(status_code=404, detail="this box runs no provider node")
        try:
            return stats_source()
        except MystError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    return application
