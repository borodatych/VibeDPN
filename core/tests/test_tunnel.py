"""The tunnel side of core: the read-only API gate, the NodeUI relay and freebind sockets."""

import asyncio
import sys
from functools import partial
from ipaddress import IPv4Network
from pathlib import Path

import pytest

from vibedpn.api.app import create_app
from vibedpn.api.tunnel import TUNNEL_READ_PATHS, TunnelGate, from_subnet, listen_socket, relay
from vibedpn.config import Config
from vibedpn.engine.myst import ProviderStats, SessionTotals

from .conftest import vps_config

TUNNEL = IPv4Network("10.78.0.0/24")
HOME_BOX = ("10.78.0.2", 51000)
STRANGER = ("203.0.113.9", 51000)


def stats() -> ProviderStats:
    return ProviderStats(
        node_version="1.39.5",
        node_uptime="1m",
        monitoring_status="unknown",
        identity=None,
        services=[],
        sessions=SessionTotals(),
    )


def gate(tmp_path: Path) -> TunnelGate:
    app = create_app(Config.model_validate(vps_config()), stats_source=stats, secrets_dir=tmp_path)
    return TunnelGate(app, TUNNEL)


def call(
    target: TunnelGate, path: str, *, method: str = "GET", client: tuple[str, int] = HOME_BOX
) -> int:
    sent: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"10.78.0.1:4480")],
        "client": client,
        "server": ("10.78.0.1", 4480),
    }
    asyncio.run(target(scope, receive, send))  # type: ignore[arg-type]
    return next(int(str(m["status"])) for m in sent if m["type"] == "http.response.start")


def test_home_boxes_read_the_allowlist(tmp_path: Path) -> None:
    target = gate(tmp_path)
    assert {"/health", "/provider/stats"} == TUNNEL_READ_PATHS
    assert call(target, "/health") == 200
    assert call(target, "/provider/stats") == 200


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/peers", "GET"),  # the keys and the addresses of the other boxes
        ("/peers/dacha/config", "GET"),
        ("/peers", "POST"),
        ("/peers/dacha", "DELETE"),
        ("/health", "POST"),
        ("/docs", "GET"),
        ("/openapi.json", "GET"),
    ],
)
def test_everything_else_is_404_over_the_tunnel(tmp_path: Path, path: str, method: str) -> None:
    assert call(gate(tmp_path), path, method=method) == 404


def test_strangers_are_refused(tmp_path: Path) -> None:
    assert call(gate(tmp_path), "/health", client=STRANGER) == 403


def test_websockets_are_closed(tmp_path: Path) -> None:
    sent: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return {"type": "websocket.connect"}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    scope = {"type": "websocket", "path": "/health", "client": HOME_BOX, "headers": []}
    asyncio.run(gate(tmp_path)(scope, receive, send))  # type: ignore[arg-type]
    assert sent == [{"type": "websocket.close", "code": 1008}]


@pytest.mark.parametrize(
    ("host", "expected"),
    [("10.78.0.2", True), ("10.79.0.2", False), ("testclient", False), (None, False)],
)
def test_from_subnet(host: object, expected: bool) -> None:
    assert from_subnet(host, TUNNEL) is expected


async def _relay_round_trip(subnet: IPv4Network, upstream_up: bool = True) -> tuple[bytes, int]:
    connections = 0

    async def upstream(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal connections
        connections += 1
        data = await reader.read()  # until the relay passes the client's EOF on
        writer.write(data.upper())
        await writer.drain()
        writer.close()

    upstream_server = await asyncio.start_server(upstream, "127.0.0.1", 0)
    upstream_port = upstream_server.sockets[0].getsockname()[1]
    if not upstream_up:
        upstream_server.close()
        await upstream_server.wait_closed()
    relay_server = await asyncio.start_server(
        partial(relay, subnet=subnet, target=("127.0.0.1", upstream_port)), "127.0.0.1", 0
    )
    relay_port = relay_server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", relay_port)
    writer.write(b"GET / HTTP/1.0\r\n\r\n")
    writer.write_eof()
    try:
        answer = await asyncio.wait_for(reader.read(), timeout=5)
    except ConnectionResetError:
        # Hanging up on a client whose request was never read makes the kernel send a reset
        # instead of a clean end; either way the client got nothing.
        answer = b""
    writer.close()
    relay_server.close()
    if upstream_up:
        upstream_server.close()
    return answer, connections


def test_relay_copies_both_directions() -> None:
    answer, connections = asyncio.run(_relay_round_trip(IPv4Network("127.0.0.0/8")))
    assert answer == b"GET / HTTP/1.0\r\n\r\n".upper()
    assert connections == 1


def test_relay_hangs_up_on_strangers_before_reaching_the_panel() -> None:
    answer, connections = asyncio.run(_relay_round_trip(TUNNEL))
    assert answer == b""
    assert connections == 0


def test_relay_hangs_up_when_the_panel_is_down() -> None:
    answer, _ = asyncio.run(_relay_round_trip(IPv4Network("127.0.0.0/8"), upstream_up=False))
    assert answer == b""


def test_plain_listen_socket() -> None:
    sock = listen_socket("127.0.0.1", 0, freebind=False)
    try:
        assert sock.getsockname()[0] == "127.0.0.1"
        assert not sock.getblocking()
    finally:
        sock.close()


@pytest.mark.skipif(sys.platform != "linux", reason="IP_FREEBIND is a Linux socket option")
def test_freebind_binds_an_address_that_does_not_exist_yet() -> None:
    sock = listen_socket("10.255.255.1", 0, freebind=True)
    try:
        assert sock.getsockname()[0] == "10.255.255.1"
    finally:
        sock.close()
    with pytest.raises(OSError):
        listen_socket("10.255.255.1", 0, freebind=False)
