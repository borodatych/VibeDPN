"""Core API and the node panel for home boxes, on the tunnel address of the VPS and nowhere else.

On role vps core listens, next to its loopback API, on the server's tunnel address — the first
host of ``wg_server.subnet``. The API there answers a read-only allowlist; the NodeUI port relays
byte for byte to the node panel published on loopback. Every connection must come from the
tunnel subnet, and the host firewall drops traffic to that subnet arriving anywhere but wg0.

The sockets are bound with ``IP_FREEBIND``: core starts before wg-server creates wg0 (compose
starts wg-server once core is healthy), and wg0 disappears whenever wg-server restarts, so the
address comes and goes under listeners that must keep working.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import socket
from collections.abc import Awaitable, Callable, Iterator, MutableMapping
from functools import partial
from ipaddress import IPv4Network, ip_address
from typing import Any

import uvicorn
from starlette.responses import JSONResponse

from vibedpn.config import Config
from vibedpn.engine.myst import NODEUI_PORT
from vibedpn.engine.wg import server_address

LOOPBACK = "127.0.0.1"
IP_FREEBIND = 15  # <linux/in.h>; Python's socket module does not name it
LISTEN_BACKLOG = 64
RELAY_CHUNK_BYTES = 64 * 1024
LOG_LEVEL = "info"
WEBSOCKET_POLICY_VIOLATION = 1008
# What a home box may read over the tunnel. Peer management and peer files stay on loopback:
# over wg0 any box could otherwise take the keys of the others.
TUNNEL_READ_PATHS = frozenset({"/health", "/provider/stats"})

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


def listen_socket(address: str, port: int, *, freebind: bool) -> socket.socket:
    """A listening TCP socket; with ``freebind`` it binds an address that does not exist yet."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if freebind:
            sock.setsockopt(socket.IPPROTO_IP, IP_FREEBIND, 1)
        sock.bind((address, port))
        sock.listen(LISTEN_BACKLOG)
        sock.setblocking(False)
    except BaseException:
        sock.close()
        raise
    return sock


def from_subnet(host: object, subnet: IPv4Network) -> bool:
    """Whether a peer address belongs to the tunnel. A TCP connection from a spoofed tunnel
    address never completes: the handshake reply is routed into wg0, not back to the spoofer."""
    if not isinstance(host, str):
        return False
    try:
        return ip_address(host) in subnet
    except ValueError:
        return False


class TunnelGate:
    """The tunnel side of the API: tunnel clients only, and only the read-only allowlist."""

    def __init__(self, app: ASGIApp, subnet: IPv4Network) -> None:
        self.app = app
        self.subnet = subnet

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            await send({"type": "websocket.close", "code": WEBSOCKET_POLICY_VIOLATION})
            return
        client = scope.get("client")
        if not from_subnet(client[0] if client else None, self.subnet):
            response = JSONResponse({"detail": "only for home boxes over the tunnel"}, 403)
        elif scope["method"] != "GET" or scope["path"] not in TUNNEL_READ_PATHS:
            response = JSONResponse({"detail": "not available over the tunnel"}, 404)
        else:
            await self.app(scope, receive, send)
            return
        await response(scope, receive, send)


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Copy one direction until it ends, then pass the end on (half-close)."""
    try:
        while chunk := await reader.read(RELAY_CHUNK_BYTES):
            writer.write(chunk)
            await writer.drain()
    except OSError:
        pass
    finally:
        if not writer.is_closing() and writer.can_write_eof():
            with contextlib.suppress(OSError):
                writer.write_eof()


async def _close(writer: asyncio.StreamWriter) -> None:
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()


async def relay(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    subnet: IPv4Network,
    target: tuple[str, int],
) -> None:
    """One connection from a home box, byte for byte to ``target``; a stranger is hung up on."""
    try:
        peer = writer.get_extra_info("peername")
        if not from_subnet(peer[0] if peer else None, subnet):
            return
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(*target)
        except OSError:
            return
        try:
            await asyncio.gather(_pipe(reader, upstream_writer), _pipe(upstream_reader, writer))
        finally:
            await _close(upstream_writer)
    finally:
        await _close(writer)


class _Server(uvicorn.Server):
    """uvicorn installs signal handlers per server, and a second server would silently replace
    the handlers of the first; the process installs one handler for all of them instead."""

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


async def serve(config: Config, application: ASGIApp) -> None:
    """The loopback API always; on role vps also the tunnel API and the NodeUI relay."""
    servers = [
        _Server(
            uvicorn.Config(application, host=LOOPBACK, port=config.api.port, log_level=LOG_LEVEL)
        )
    ]
    sockets: list[list[socket.socket] | None] = [None]
    relays: list[asyncio.Server] = []
    if config.wg_server is not None:
        address = str(server_address(config).ip)
        subnet = config.wg_server.subnet
        gate = TunnelGate(application, subnet)
        servers.append(_Server(uvicorn.Config(gate, lifespan="off", log_level=LOG_LEVEL)))
        sockets.append([listen_socket(address, config.api.port, freebind=True)])
        relays.append(
            await asyncio.start_server(
                partial(relay, subnet=subnet, target=(LOOPBACK, NODEUI_PORT)),
                sock=listen_socket(address, NODEUI_PORT, freebind=True),
            )
        )

    def stop() -> None:
        for server in servers:
            server.should_exit = True
        for relay_server in relays:
            relay_server.close()

    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop)
    try:
        await asyncio.gather(
            *(server.serve(sockets=bound) for server, bound in zip(servers, sockets, strict=True))
        )
    finally:
        stop()


def run_servers(config: Config, application: ASGIApp) -> None:
    asyncio.run(serve(config, application))
