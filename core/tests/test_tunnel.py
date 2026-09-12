"""The tunnel side of core: the read-only API gate, the NodeUI relay, listeners and serving."""

import asyncio
import os
import signal
import sys
import time
from functools import partial
from ipaddress import IPv4Network
from pathlib import Path

import httpx
import pytest

from vibedpn.api.app import create_app
from vibedpn.api.tunnel import (
    TUNNEL_READ_PATHS,
    Listeners,
    RelayLimits,
    TunnelGate,
    from_subnet,
    listen_socket,
    relay,
    run_servers,
    serve,
)
from vibedpn.config import Config
from vibedpn.engine.myst import ProviderStats, SessionTotals

from .conftest import home_config, vps_config

TUNNEL = IPv4Network("10.78.0.0/24")
LOCAL = IPv4Network("127.0.0.0/8")
HOME_BOX = ("10.78.0.2", 51000)
STRANGER = ("203.0.113.9", 51000)
REQUEST = b"GET / HTTP/1.0\r\n\r\n"


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


# --- the API gate ----------------------------------------------------------------------------


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
        ("/health/", "GET"),
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


# --- the NodeUI relay ------------------------------------------------------------------------


async def _read_all(reader: asyncio.StreamReader) -> bytes:
    try:
        return await asyncio.wait_for(reader.read(), timeout=5)
    except ConnectionResetError:
        # Hanging up on a client whose request was never read makes the kernel send a reset
        # instead of a clean end; either way the client got nothing.
        return b""


async def _upstream(handler: object) -> tuple[asyncio.Server, int]:
    server = await asyncio.start_server(handler, "127.0.0.1", 0)  # type: ignore[arg-type]
    return server, server.sockets[0].getsockname()[1]


async def _relay(subnet: IPv4Network, port: int, limits: RelayLimits) -> tuple[asyncio.Server, int]:
    handler = partial(relay, subnet=subnet, target=("127.0.0.1", port), limits=limits)
    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


async def _round_trip(
    subnet: IPv4Network, limits: RelayLimits, *, upstream_up: bool = True
) -> tuple[bytes, int]:
    seen = 0

    async def upper(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal seen
        seen += 1
        writer.write((await reader.read()).upper())  # until the relay passes the client's EOF on
        await writer.drain()
        writer.close()

    upstream, upstream_port = await _upstream(upper)
    if not upstream_up:
        upstream.close()
        await upstream.wait_closed()
    relay_server, relay_port = await _relay(subnet, upstream_port, limits)
    reader, writer = await asyncio.open_connection("127.0.0.1", relay_port)
    writer.write(REQUEST)
    writer.write_eof()
    answer = await _read_all(reader)
    writer.close()
    relay_server.close()
    upstream.close()
    return answer, seen


def test_relay_copies_both_directions() -> None:
    assert asyncio.run(_round_trip(LOCAL, RelayLimits())) == (REQUEST.upper(), 1)


def test_relay_hangs_up_on_strangers_before_reaching_the_panel() -> None:
    assert asyncio.run(_round_trip(TUNNEL, RelayLimits())) == (b"", 0)


def test_relay_hangs_up_when_the_panel_is_down() -> None:
    answer, _ = asyncio.run(_round_trip(LOCAL, RelayLimits(), upstream_up=False))
    assert answer == b""


def test_relay_refuses_connections_over_the_cap() -> None:
    assert asyncio.run(_round_trip(LOCAL, RelayLimits(max_connections=0))) == (b"", 0)


def test_relay_closes_a_client_that_went_silent() -> None:
    async def scenario() -> float:
        async def silent(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            await reader.read()

        upstream, upstream_port = await _upstream(silent)
        limits = RelayLimits(idle_seconds=0.2, grace_seconds=0.2)
        relay_server, relay_port = await _relay(LOCAL, upstream_port, limits)
        reader, writer = await asyncio.open_connection("127.0.0.1", relay_port)
        started = time.monotonic()
        assert await _read_all(reader) == b""  # nobody said a word: the relay hangs up
        elapsed = time.monotonic() - started
        # The client sees the end as soon as the relay half-closes; the slot is released a moment
        # later, once the upstream side is closed too.
        for _ in range(20):
            if limits.active == 0:
                break
            await asyncio.sleep(0.1)
        assert limits.active == 0
        writer.close()
        relay_server.close()
        upstream.close()
        return elapsed

    assert asyncio.run(scenario()) < 3


def test_a_client_silent_after_its_answer_frees_its_slot() -> None:
    """The panel answered and closed; the client never does. After the grace period the relay
    closes it, so the next box is served instead of refused over the cap."""

    async def scenario() -> bytes:
        async def line(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            writer.write((await reader.readline()).upper())
            await writer.drain()
            writer.close()

        upstream, upstream_port = await _upstream(line)
        limits = RelayLimits(max_connections=1, grace_seconds=0.2)
        relay_server, relay_port = await _relay(LOCAL, upstream_port, limits)
        first_reader, first_writer = await asyncio.open_connection("127.0.0.1", relay_port)
        first_writer.write(b"first\n")
        assert await first_reader.readline() == b"FIRST\n"
        await asyncio.sleep(0.6)  # the first client stays connected and silent
        second_reader, second_writer = await asyncio.open_connection("127.0.0.1", relay_port)
        second_writer.write(b"second\n")
        answer = await asyncio.wait_for(second_reader.readline(), timeout=5)
        for writer in (first_writer, second_writer):
            writer.close()
        relay_server.close()
        upstream.close()
        return answer

    assert asyncio.run(scenario()) == b"SECOND\n"


# --- listeners and serving -------------------------------------------------------------------


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


def test_serve_answers_both_ports_and_stops_on_sigterm(tmp_path: Path) -> None:
    """The loopback API, the tunnel API and the relay together; one SIGTERM stops them all,
    even with a relayed connection still open."""

    async def scenario() -> None:
        async def panel(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            await reader.read()

        upstream, upstream_port = await _upstream(panel)
        app = create_app(
            Config.model_validate(vps_config()), stats_source=stats, secrets_dir=tmp_path
        )
        listeners = Listeners(
            loopback_api=listen_socket("127.0.0.1", 0, freebind=False),
            tunnel_api=listen_socket("127.0.0.1", 0, freebind=False),
            nodeui=listen_socket("127.0.0.1", 0, freebind=False),
            subnet=LOCAL,
            nodeui_target=("127.0.0.1", upstream_port),
        )
        loopback, tunnel, nodeui = (
            sock.getsockname()[1]
            for sock in (listeners.loopback_api, listeners.tunnel_api, listeners.nodeui)
            if sock is not None
        )
        serving = asyncio.create_task(serve(app, listeners))
        async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
            for _ in range(50):
                try:
                    if (await client.get(f"http://127.0.0.1:{tunnel}/health")).status_code == 200:
                        break
                except httpx.TransportError:
                    await asyncio.sleep(0.1)
            assert (await client.get(f"http://127.0.0.1:{loopback}/peers")).status_code == 200
            assert (await client.get(f"http://127.0.0.1:{tunnel}/peers")).status_code == 404
        _, relayed = await asyncio.open_connection("127.0.0.1", nodeui)
        await asyncio.sleep(0.1)
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(serving, timeout=10)
        relayed.close()
        upstream.close()
        listeners.close()

    asyncio.run(scenario())


def test_a_taken_port_is_one_line_at_start(capsys: pytest.CaptureFixture[str]) -> None:
    taken = listen_socket("127.0.0.1", 0, freebind=False)
    port = taken.getsockname()[1]
    raw = home_config()
    raw["api"] = {"port": port}
    try:
        with pytest.raises(SystemExit) as exit_info:
            run_servers(Config.model_validate(raw), create_app())
    finally:
        taken.close()
    assert exit_info.value.code == os.EX_UNAVAILABLE
    assert f"vibedpn-core: cannot start: cannot listen on port {port}" in capsys.readouterr().err
