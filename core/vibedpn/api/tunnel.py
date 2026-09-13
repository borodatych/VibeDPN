"""Core API and the node panel for home boxes, on the tunnel address of the VPS and nowhere else.

On role vps core listens, next to its loopback API, on the server's tunnel address — the first
host of ``wg_server.subnet``. The API there answers a read-only allowlist; the NodeUI port relays
byte for byte to the node panel published on loopback. Every connection must come from the
tunnel subnet, and the host firewall drops traffic to that subnet arriving anywhere but wg0.

The tunnel sockets are bound with ``IP_FREEBIND``: core starts before wg-server creates wg0
(compose starts wg-server once core is healthy), and wg0 disappears whenever wg-server restarts,
so the address comes and goes under listeners that must keep working. All sockets are opened
before serving, so a taken port is one clear line at start, not a traceback from inside uvicorn.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import socket
import sys
from collections.abc import Awaitable, Callable, Coroutine, Iterator, MutableMapping, Sequence
from dataclasses import dataclass, field
from functools import partial
from ipaddress import IPv4Network, ip_address
from typing import Any

import uvicorn
from starlette.responses import JSONResponse

from vibedpn.api.discovery import watch_devices
from vibedpn.api.uplink import watch_uplink
from vibedpn.config import Config, Upstream
from vibedpn.engine.devices import DeviceStore
from vibedpn.engine.myst import NODEUI_PORT
from vibedpn.engine.wg import server_address

LOOPBACK = "127.0.0.1"
IP_FREEBIND = 15  # <linux/in.h>; Python's socket module does not name it
LISTEN_BACKLOG = 64
LOG_LEVEL = "info"
WEBSOCKET_POLICY_VIOLATION = 1008
# What a home box may read over the tunnel. Peer management and peer files stay on loopback:
# over wg0 any box could otherwise take the keys of the others.
TUNNEL_READ_PATHS = frozenset({"/health", "/provider/stats"})
TUNNEL_API_CONCURRENCY = 64
# The relay must not keep a connection whose peer went silent: a laptop that sleeps or loses
# the tunnel sends neither FIN nor RST, because WireGuard drops the path without a word.
RELAY_CHUNK_BYTES = 64 * 1024
RELAY_IDLE_SECONDS = 600.0
RELAY_HALF_CLOSE_GRACE_SECONDS = 30.0
RELAY_CONNECT_SECONDS = 5.0
RELAY_MAX_CONNECTIONS = 128
KEEPALIVE_IDLE_SECONDS = 60
KEEPALIVE_INTERVAL_SECONDS = 10
KEEPALIVE_PROBES = 5

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


def enable_keepalive(sock: socket.socket | None) -> None:
    """TCP keepalive on a relayed connection, so the kernel notices a peer that vanished."""
    if sock is None:
        return
    with contextlib.suppress(OSError):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        if hasattr(socket, "TCP_KEEPIDLE"):  # Linux; macOS names the idle time differently
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, KEEPALIVE_IDLE_SECONDS)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, KEEPALIVE_INTERVAL_SECONDS)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, KEEPALIVE_PROBES)


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


async def _pipe(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, idle_seconds: float
) -> None:
    """Copy one direction until it ends or stays idle too long, then pass the end on."""
    try:
        while True:
            async with asyncio.timeout(idle_seconds):
                chunk = await reader.read(RELAY_CHUNK_BYTES)
                if not chunk:
                    break
                writer.write(chunk)
                await writer.drain()  # a peer that stops reading counts as idle too
    except (OSError, TimeoutError):
        pass
    finally:
        if not writer.is_closing() and writer.can_write_eof():
            with contextlib.suppress(OSError):
                writer.write_eof()


async def _close(writer: asyncio.StreamWriter) -> None:
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()


@dataclass
class RelayLimits:
    idle_seconds: float = RELAY_IDLE_SECONDS
    grace_seconds: float = RELAY_HALF_CLOSE_GRACE_SECONDS
    connect_seconds: float = RELAY_CONNECT_SECONDS
    max_connections: int = RELAY_MAX_CONNECTIONS
    active: int = 0


async def relay(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    subnet: IPv4Network,
    target: tuple[str, int],
    limits: RelayLimits,
) -> None:
    """One connection from a home box, byte for byte to ``target``.

    A stranger, or a box over the connection cap, is hung up on. Once either side finishes, the
    other gets a short grace period and then both are closed, so a client that disappeared after
    its answer never pins a socket and a task for good.
    """
    try:
        peer = writer.get_extra_info("peername")
        if not from_subnet(peer[0] if peer else None, subnet):
            return
        if limits.active >= limits.max_connections:
            return
        limits.active += 1
        try:
            await _relay_open(reader, writer, target, limits)
        finally:
            limits.active -= 1
    finally:
        await _close(writer)


async def _relay_open(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    target: tuple[str, int],
    limits: RelayLimits,
) -> None:
    enable_keepalive(writer.get_extra_info("socket"))
    try:
        async with asyncio.timeout(limits.connect_seconds):
            upstream_reader, upstream_writer = await asyncio.open_connection(*target)
    except (OSError, TimeoutError):
        return
    try:
        directions = {
            asyncio.create_task(_pipe(reader, upstream_writer, limits.idle_seconds)),
            asyncio.create_task(_pipe(upstream_reader, writer, limits.idle_seconds)),
        }
        _, pending = await asyncio.wait(directions, return_when=asyncio.FIRST_COMPLETED)
        if pending:
            _, pending = await asyncio.wait(pending, timeout=limits.grace_seconds)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    finally:
        await _close(upstream_writer)


@dataclass
class Listeners:
    """Every socket core serves, opened before serving."""

    loopback_api: socket.socket
    tunnel_api: socket.socket | None = None
    nodeui: socket.socket | None = None
    subnet: IPv4Network | None = None
    nodeui_target: tuple[str, int] = (LOOPBACK, NODEUI_PORT)
    limits: RelayLimits = field(default_factory=RelayLimits)

    def close(self) -> None:
        for sock in (self.loopback_api, self.tunnel_api, self.nodeui):
            if sock is not None:
                sock.close()


def open_listeners(config: Config) -> Listeners:
    """The loopback API always; on role vps also the tunnel API and the NodeUI relay."""
    listeners = Listeners(listen_socket(LOOPBACK, config.api.port, freebind=False))
    if config.wg_server is None:
        return listeners
    address = str(server_address(config).ip)
    try:
        listeners.tunnel_api = listen_socket(address, config.api.port, freebind=True)
        listeners.nodeui = listen_socket(address, NODEUI_PORT, freebind=True)
    except BaseException:
        listeners.close()
        raise
    listeners.subnet = config.wg_server.subnet
    return listeners


class _Server(uvicorn.Server):
    """uvicorn installs signal handlers per server, and a second server would silently replace
    the handlers of the first; the process installs one handler for all of them instead."""

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


async def serve(
    application: ASGIApp,
    listeners: Listeners,
    background: Sequence[Callable[[], Coroutine[Any, Any, None]]] = (),
) -> None:
    """Serve every listener until SIGTERM or SIGINT stops them all together; ``background``
    coroutines (the uplink watcher) run alongside and are cancelled with them."""
    servers: list[tuple[_Server, socket.socket]] = [
        (_Server(uvicorn.Config(application, log_level=LOG_LEVEL)), listeners.loopback_api)
    ]
    relays: list[asyncio.Server] = []
    if listeners.subnet is not None and listeners.tunnel_api is not None:
        gate = TunnelGate(application, listeners.subnet)
        tunnel = uvicorn.Config(
            gate, lifespan="off", log_level=LOG_LEVEL, limit_concurrency=TUNNEL_API_CONCURRENCY
        )
        servers.append((_Server(tunnel), listeners.tunnel_api))
    if listeners.subnet is not None and listeners.nodeui is not None:
        handler = partial(
            relay, subnet=listeners.subnet, target=listeners.nodeui_target, limits=listeners.limits
        )
        relays.append(await asyncio.start_server(handler, sock=listeners.nodeui))

    def stop() -> None:
        for server, _ in servers:
            server.should_exit = True
        for relay_server in relays:
            relay_server.close()

    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop)
    tasks = [asyncio.create_task(start()) for start in background]
    try:
        await asyncio.gather(*(server.serve(sockets=[sock]) for server, sock in servers))
    finally:
        stop()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(signum)


def run_servers(
    config: Config,
    application: ASGIApp,
    *,
    uplinks: Sequence[Upstream] = (),
    devices: DeviceStore | None = None,
) -> None:
    try:
        listeners = open_listeners(config)
    except OSError as exc:
        sys.stderr.write(
            f"vibedpn-core: cannot start: cannot listen on port {config.api.port}"
            f" or {NODEUI_PORT}: {exc.strerror}\n"
        )
        raise SystemExit(os.EX_UNAVAILABLE) from None
    try:
        background: list[Callable[[], Coroutine[Any, Any, None]]] = []
        background.extend(partial(watch_uplink, uplink) for uplink in uplinks)
        if devices is not None:
            background.append(partial(watch_devices, config, devices))
        asyncio.run(serve(application, listeners, background))
    finally:
        listeners.close()
