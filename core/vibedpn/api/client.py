"""Client of the core API for the CLI: ``vibedpn status`` reads the node through ``core``.

The CLI never talks to TequilAPI itself: ``core`` is the one process that knows the node, and
routing every reader through it keeps one place to change when the node moves (Stage 3 puts
the API behind the tunnel).
"""

from __future__ import annotations

import httpx
from pydantic import ValidationError

from vibedpn.engine.myst import STATS_DEADLINE_SECONDS, ProviderStats

CORE_API_HOST = "127.0.0.1"
# Core may legitimately spend the whole node deadline before answering; wait past it.
CORE_API_TIMEOUT_SECONDS = STATS_DEADLINE_SECONDS + 2.0


class CoreUnreachableError(RuntimeError):
    """``core`` is not listening: the box is down or still starting."""


class StatsUnavailableError(RuntimeError):
    """``core`` answered, but without statistics; the text is its ``detail``."""


def fetch_provider_stats(port: int, transport: httpx.BaseTransport | None = None) -> ProviderStats:
    url = f"http://{CORE_API_HOST}:{port}/provider/stats"
    try:
        with httpx.Client(
            timeout=CORE_API_TIMEOUT_SECONDS, transport=transport, trust_env=False
        ) as client:
            response = client.get(url)
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        raise CoreUnreachableError(f"{exc.__class__.__name__}: {exc}") from exc
    except httpx.HTTPError as exc:
        # Core accepted the connection but did not answer in time or in one piece.
        raise StatsUnavailableError(
            f"no answer from core: {exc.__class__.__name__}: {exc}"
        ) from exc
    if response.status_code != httpx.codes.OK:
        raise StatsUnavailableError(_detail(response))
    try:
        return ProviderStats.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        raise StatsUnavailableError(
            "core answered something that is not provider stats (CLI and core versions differ?)"
        ) from exc


def _detail(response: httpx.Response) -> str:
    try:
        body: object = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and isinstance(body.get("detail"), str):
        return str(body["detail"])
    return f"HTTP {response.status_code}"
