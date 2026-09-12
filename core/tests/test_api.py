"""Core API and the CLI-side client of it."""

import httpx
import pytest
from fastapi.testclient import TestClient

from vibedpn import __version__
from vibedpn.api.app import create_app
from vibedpn.api.client import CoreUnreachableError, StatsUnavailableError, fetch_provider_stats
from vibedpn.config import Config
from vibedpn.engine.myst import MystError, ProviderStats, SessionTotals

from .conftest import home_config, vps_config


def stats() -> ProviderStats:
    return ProviderStats(
        node_version="1.39.5",
        node_uptime="1m",
        monitoring_status="unknown",
        identity=None,
        services=[],
        sessions=SessionTotals(),
    )


def test_health() -> None:
    response = TestClient(create_app()).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_provider_stats_returns_what_the_node_said() -> None:
    app = create_app(Config.model_validate(vps_config()), stats_source=stats)
    response = TestClient(app).get("/provider/stats")
    assert response.status_code == 200
    assert ProviderStats.model_validate(response.json()) == stats()


def test_provider_stats_is_503_when_the_node_is_unreachable() -> None:
    def down() -> ProviderStats:
        raise MystError("TequilAPI /healthcheck: ConnectError: refused")

    app = create_app(Config.model_validate(vps_config()), stats_source=down)
    response = TestClient(app).get("/provider/stats")
    assert response.status_code == 503
    assert response.json() == {"detail": "TequilAPI /healthcheck: ConnectError: refused"}


def test_provider_stats_is_404_without_a_provider() -> None:
    raw = home_config()
    raw["provider"] = {"enabled": False}
    for config in (None, Config.model_validate(raw)):
        response = TestClient(create_app(config, stats_source=stats)).get("/provider/stats")
        assert response.status_code == 404


def test_client_reads_stats_from_core() -> None:
    def core(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://127.0.0.1:4480/provider/stats"
        return httpx.Response(200, content=stats().model_dump_json())

    assert fetch_provider_stats(4480, transport=httpx.MockTransport(core)) == stats()


def test_client_reports_core_down() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(CoreUnreachableError, match="ConnectError"):
        fetch_provider_stats(4480, transport=httpx.MockTransport(refuse))


def test_client_distinguishes_a_slow_core_from_a_missing_one() -> None:
    """core accepted the connection: a timeout is "no answer", not "not running"."""

    def stall(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(StatsUnavailableError, match="no answer from core: ReadTimeout"):
        fetch_provider_stats(4480, transport=httpx.MockTransport(stall))


@pytest.mark.parametrize(
    "body",
    ["<html>not json</html>", "{}", '{"detail": "x"}', '{"node_version": "1.39.5"}'],
)
def test_client_rejects_a_200_that_is_not_provider_stats(body: str) -> None:
    """Another process on api.port, or a CLI older than the image: no traceback."""
    reply = httpx.Response(200, content=body)
    with pytest.raises(StatsUnavailableError, match="not provider stats"):
        fetch_provider_stats(4480, transport=httpx.MockTransport(lambda _request: reply))


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(503, json={"detail": "TequilAPI /healthcheck: HTTP 500"}), "HTTP 500"),
        (httpx.Response(502, content="<html>bad gateway</html>"), "HTTP 502"),
    ],
)
def test_client_reports_missing_stats(response: httpx.Response, expected: str) -> None:
    with pytest.raises(StatsUnavailableError, match=expected):
        fetch_provider_stats(4480, transport=httpx.MockTransport(lambda _request: response))
