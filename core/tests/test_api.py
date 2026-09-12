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


# --- tunnel peers ---------------------------------------------------------------------------

from datetime import UTC, datetime  # noqa: E402
from ipaddress import IPv4Address  # noqa: E402
from pathlib import Path  # noqa: E402

from vibedpn.api import client as core_api  # noqa: E402
from vibedpn.api.models import PeerFile, PeerView  # noqa: E402
from vibedpn.engine.wg import PeerLink  # noqa: E402

PEER_LINK = PeerLink("203.0.113.7:40312", 1789236372, 15432, 9876)


def tunnel_app(tmp_path: Path, links: dict[str, PeerLink] | None = None) -> TestClient:
    app = create_app(
        Config.model_validate(vps_config()),
        stats_source=stats,
        secrets_dir=tmp_path,
        link_source=lambda: links,
    )
    return TestClient(app)


def test_peer_lifecycle_over_the_api(tmp_path: Path) -> None:
    api = tunnel_app(tmp_path)
    created = api.post("/peers", json={"name": "dacha"})
    assert created.status_code == 201
    body = PeerFile.model_validate(created.json())
    assert body.address == IPv4Address("10.78.0.2") and "[Interface]" in body.config
    private_key = body.config.split("PrivateKey = ", 1)[1].split("\n", 1)[0]

    listed = api.get("/peers")
    assert listed.status_code == 200
    assert private_key not in listed.text and "private_key" not in listed.text
    assert [PeerView.model_validate(p).name for p in listed.json()] == ["dacha"]

    exported = api.get("/peers/dacha/config")
    assert exported.status_code == 200 and exported.json()["config"] == body.config

    assert api.delete("/peers/dacha").status_code == 204
    assert api.get("/peers").json() == []


def test_peer_errors_map_to_http_statuses(tmp_path: Path) -> None:
    api = tunnel_app(tmp_path)
    api.post("/peers", json={"name": "dacha"})
    duplicate = api.post("/peers", json={"name": "dacha"})
    assert duplicate.status_code == 409 and "already exists" in duplicate.json()["detail"]
    assert api.post("/peers", json={"name": "Bad Name"}).status_code == 422
    assert api.delete("/peers/ghost").status_code == 404
    assert api.get("/peers/ghost/config").status_code == 404


def test_peer_list_carries_the_live_state(tmp_path: Path) -> None:
    api = tunnel_app(tmp_path)
    public = PeerFile.model_validate(api.post("/peers", json={"name": "dacha"}).json())
    registered = api.get("/peers").json()[0]["public_key"]
    live = tunnel_app(tmp_path, {registered: PEER_LINK}).get("/peers").json()[0]
    assert (live["endpoint"], live["latest_handshake"], live["rx_bytes"], live["tx_bytes"]) == (
        "203.0.113.7:40312",
        1789236372,
        15432,
        9876,
    )
    unknown = tunnel_app(tmp_path, None).get("/peers").json()[0]
    assert unknown["latest_handshake"] is None and public.name == "dacha"


def test_peers_are_404_without_a_tunnel(tmp_path: Path) -> None:
    home = TestClient(create_app(Config.model_validate(home_config()), secrets_dir=tmp_path))
    assert home.get("/peers").status_code == 404
    unconfigured = TestClient(create_app(Config.model_validate(vps_config())))
    assert unconfigured.post("/peers", json={"name": "dacha"}).status_code == 404


def test_client_peer_calls(tmp_path: Path) -> None:
    api = tunnel_app(tmp_path)

    def core(request: httpx.Request) -> httpx.Response:
        forwarded = api.request(
            request.method,
            request.url.path,
            content=request.content or None,
            headers={"content-type": "application/json"},
        )
        return httpx.Response(forwarded.status_code, content=forwarded.content)

    transport = httpx.MockTransport(core)
    added = core_api.add_peer(4480, "dacha", transport=transport)
    assert added.name == "dacha"
    assert [p.name for p in core_api.list_peers(4480, transport=transport)] == ["dacha"]
    assert core_api.export_peer(4480, "dacha", transport=transport).config == added.config
    with pytest.raises(core_api.PeerRequestError, match="already exists"):
        core_api.add_peer(4480, "dacha", transport=transport)
    core_api.remove_peer(4480, "dacha", transport=transport)
    with pytest.raises(core_api.PeerRequestError, match="no peer named"):
        core_api.remove_peer(4480, "dacha", transport=transport)


def test_client_peer_calls_report_transport_and_version_problems() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    def stall(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(CoreUnreachableError):
        core_api.list_peers(4480, transport=httpx.MockTransport(refuse))
    with pytest.raises(core_api.PeerRequestError, match="no answer from core"):
        core_api.list_peers(4480, transport=httpx.MockTransport(stall))
    odd = httpx.MockTransport(lambda _r: httpx.Response(200, content=b'{"hello": 1}'))
    with pytest.raises(core_api.PeerRequestError, match="versions differ"):
        core_api.list_peers(4480, transport=odd)
    with pytest.raises(core_api.PeerRequestError, match="versions differ"):
        core_api.export_peer(4480, "dacha", transport=odd)


def test_created_timestamps_are_timezone_aware(tmp_path: Path) -> None:
    api = tunnel_app(tmp_path)
    api.post("/peers", json={"name": "dacha"})
    created = PeerView.model_validate(api.get("/peers").json()[0]).created
    assert created.tzinfo is not None and created <= datetime.now(UTC)


def test_tunnel_only_over_the_api(tmp_path: Path) -> None:
    api = tunnel_app(tmp_path)
    created = api.post("/peers", json={"name": "laptop", "tunnel_only": True})
    assert created.status_code == 201
    assert "AllowedIPs = 10.78.0.0/24" in created.json()["config"]
    assert api.get("/peers").json()[0]["tunnel_only"] is True


def test_peer_list_tells_pending_from_unknown(tmp_path: Path) -> None:
    api = tunnel_app(tmp_path)
    api.post("/peers", json={"name": "dacha"})
    api.post("/peers", json={"name": "flat"})
    keys = {p["name"]: p["public_key"] for p in api.get("/peers").json()}
    live = {
        p["name"]: p["applied"]
        for p in tunnel_app(tmp_path, {keys["dacha"]: PEER_LINK}).get("/peers").json()
    }
    assert live == {"dacha": True, "flat": False}  # flat is registered, wg0 does not have it yet
    unreadable = tunnel_app(tmp_path, None).get("/peers").json()
    assert [p["applied"] for p in unreadable] == [None, None]
