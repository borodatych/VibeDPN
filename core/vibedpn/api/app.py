"""ASGI application factory. Routes grow stage by stage; Stage 0 serves ``/health`` only."""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from vibedpn import __version__


class Health(BaseModel):
    """Liveness answer used by the container healthcheck."""

    status: Literal["ok"]
    version: str


def create_app() -> FastAPI:
    """Build the application. A factory keeps tests free of import-time side effects."""
    application = FastAPI(title="VibeDPN core API", version=__version__)

    @application.get("/health", response_model=Health)
    def health() -> Health:
        return Health(status="ok", version=__version__)

    return application


app = create_app()
