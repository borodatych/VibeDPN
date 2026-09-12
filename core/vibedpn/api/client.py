"""Client of the core API for the CLI.

The CLI never talks to TequilAPI or touches ``secrets/`` itself: ``core`` is the one process
that knows the node and owns the tunnel files (``secrets/`` is root-only), and routing every
reader and writer through it keeps one place to change when the API moves behind the tunnel.
"""

from __future__ import annotations

from urllib.parse import quote

import httpx
from pydantic import TypeAdapter, ValidationError

from vibedpn.api.models import PeerCreate, PeerFile, PeerView
from vibedpn.engine.myst import STATS_DEADLINE_SECONDS, ProviderStats

CORE_API_HOST = "127.0.0.1"
# Core may legitimately spend the whole node deadline before answering; wait past it.
CORE_API_TIMEOUT_SECONDS = STATS_DEADLINE_SECONDS + 2.0
VERSION_HINT = "CLI and core versions differ?"
PEER_LIST: TypeAdapter[list[PeerView]] = TypeAdapter(list[PeerView])


class CoreUnreachableError(RuntimeError):
    """``core`` is not listening: the box is down or still starting."""


class CoreNoAnswerError(RuntimeError):
    """``core`` accepted the connection but did not answer in time or in one piece."""


class StatsUnavailableError(RuntimeError):
    """``core`` answered, but without statistics; the text is its ``detail``."""


class PeerRequestError(RuntimeError):
    """``core`` refused or failed a peer request; the text is its ``detail``."""


def _send(
    port: int,
    method: str,
    path: str,
    *,
    body: dict[str, str | bool] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> httpx.Response:
    url = f"http://{CORE_API_HOST}:{port}{path}"
    try:
        with httpx.Client(
            timeout=CORE_API_TIMEOUT_SECONDS, transport=transport, trust_env=False
        ) as client:
            return client.request(method, url, json=body)
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        raise CoreUnreachableError(f"{exc.__class__.__name__}: {exc}") from exc
    except httpx.HTTPError as exc:
        raise CoreNoAnswerError(f"no answer from core: {exc.__class__.__name__}: {exc}") from exc


def _detail(response: httpx.Response) -> str:
    try:
        body: object = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and isinstance(body.get("detail"), str):
        return str(body["detail"])
    return f"HTTP {response.status_code}"


def fetch_provider_stats(port: int, transport: httpx.BaseTransport | None = None) -> ProviderStats:
    try:
        response = _send(port, "GET", "/provider/stats", transport=transport)
    except CoreNoAnswerError as exc:
        raise StatsUnavailableError(str(exc)) from exc
    if response.status_code != httpx.codes.OK:
        raise StatsUnavailableError(_detail(response))
    try:
        return ProviderStats.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        raise StatsUnavailableError(
            f"core answered something that is not provider stats ({VERSION_HINT})"
        ) from exc


def _peer_request(
    port: int,
    method: str,
    path: str,
    expected: int,
    *,
    body: dict[str, str | bool] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> httpx.Response:
    try:
        response = _send(port, method, path, body=body, transport=transport)
    except CoreNoAnswerError as exc:
        raise PeerRequestError(str(exc)) from exc
    if response.status_code != expected:
        raise PeerRequestError(_detail(response))
    return response


def _peer_file(response: httpx.Response) -> PeerFile:
    try:
        return PeerFile.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        raise PeerRequestError(
            f"core answered something that is not a peer file ({VERSION_HINT})"
        ) from exc


def list_peers(port: int, transport: httpx.BaseTransport | None = None) -> list[PeerView]:
    response = _peer_request(port, "GET", "/peers", httpx.codes.OK, transport=transport)
    try:
        return PEER_LIST.validate_python(response.json())
    except (ValueError, ValidationError) as exc:
        raise PeerRequestError(
            f"core answered something that is not a peer list ({VERSION_HINT})"
        ) from exc


def add_peer(
    port: int,
    name: str,
    transport: httpx.BaseTransport | None = None,
    *,
    tunnel_only: bool = False,
) -> PeerFile:
    body = PeerCreate(name=name, tunnel_only=tunnel_only).model_dump()
    return _peer_file(
        _peer_request(port, "POST", "/peers", httpx.codes.CREATED, body=body, transport=transport)
    )


def export_peer(port: int, name: str, transport: httpx.BaseTransport | None = None) -> PeerFile:
    path = f"/peers/{quote(name, safe='')}/config"
    return _peer_file(_peer_request(port, "GET", path, httpx.codes.OK, transport=transport))


def remove_peer(port: int, name: str, transport: httpx.BaseTransport | None = None) -> None:
    path = f"/peers/{quote(name, safe='')}"
    _peer_request(port, "DELETE", path, httpx.codes.NO_CONTENT, transport=transport)
