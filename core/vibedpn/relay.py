"""The SNI relay of the Mysterium nodes (docs/decisions.md, 22).

An ISP that blocks Mysterium by name drops every TLS connection whose first record carries
``mysterium.network`` in its server name. The same server answers when that name is cut across two
TLS records: the filter compares the string in one record, the server reassembles the handshake.

So the nodes send their TLS to this relay (their ``extra_hosts`` point the blocked names here) and
it forwards the bytes to the real address. Nothing is decrypted and no certificate is replaced: the
node still verifies the server itself, exactly as without the relay. Whether a name needs the cut is
decided per name: the first connection goes as it is, and only a name whose handshake stays silent
is retried split — on a fresh upstream connection, before the client has seen a single byte.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import socket
import struct
import sys
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

RELAY_PORT = 443
# A container of the gateway network; the host router drops LAN traffic addressed to that subnet.
DEFAULT_ADDRESS = "0.0.0.0"
# Only the zone the nodes are blocked in: the relay must never become an open proxy.
DEFAULT_ZONE = "mysterium.network"
CONNECT_TIMEOUT = 8.0
# A server answers a ClientHello in milliseconds; this much silence means the filter swallowed it.
HANDSHAKE_TIMEOUT = 6.0
HELLO_TIMEOUT = 10.0
MAX_HELLO_BYTES = 16 * 1024
RECORD_HEADER = 5
HANDSHAKE_RECORD = 0x16
CLIENT_HELLO = 0x01
SERVER_NAME_EXTENSION = 0x00
HOST_NAME_TYPE = 0x00
RANDOM_BYTES = 32

Resolve = Callable[[str], Coroutine[Any, Any, tuple[str, int]]]


def _to_stderr(message: str) -> None:
    sys.stderr.write(f"vibedpn-relay: {message}\n")


class RelayError(RuntimeError):
    """A connection this relay cannot serve, with the reason the owner reads in the log."""


def _u16(data: bytes, at: int) -> int:
    if at + 2 > len(data):
        raise RelayError("the TLS record ends in the middle of a length")
    return int(struct.unpack_from(">H", data, at)[0])


def server_name(hello: bytes) -> tuple[str, int]:
    """The server name of a ClientHello record and where it starts inside the record.

    ``hello`` is one whole TLS record, header included; the offset is what ``split_hello`` cuts at.
    """
    if len(hello) < RECORD_HEADER or hello[0] != HANDSHAKE_RECORD:
        raise RelayError("not a TLS handshake record")
    at = RECORD_HEADER
    if len(hello) <= at or hello[at] != CLIENT_HELLO:
        raise RelayError("the first record is not a ClientHello")
    at += 4 + 2 + RANDOM_BYTES  # handshake header, legacy version, random
    at += 1 + hello[at] if at < len(hello) else 0  # session id
    at += 2 + _u16(hello, at)  # cipher suites
    at += 1 + hello[at] if at < len(hello) else 0  # compression methods
    end = at + 2 + _u16(hello, at)
    at += 2
    while at + 4 <= min(end, len(hello)):
        kind, size = _u16(hello, at), _u16(hello, at + 2)
        at += 4
        if kind != SERVER_NAME_EXTENSION:
            at += size
            continue
        # server_name_list: 2 bytes of list length, then entries of type + 2-byte length
        entry = at + 2
        while entry + 3 <= at + size:
            name_type, length = hello[entry], _u16(hello, entry + 1)
            start = entry + 3
            if name_type == HOST_NAME_TYPE:
                return hello[start : start + length].decode(
                    "ascii", errors="replace"
                ).lower(), start
            entry = start + length
        break
    raise RelayError("the ClientHello names no server")


def split_hello(hello: bytes, at: int) -> bytes:
    """The same ClientHello as two TLS records, the cut at ``at`` (inside the server name).

    The handshake bytes are untouched: only the record framing around them changes, which every TLS
    server reassembles and a filter comparing one record does not.
    """
    version, payload = hello[1:3], hello[RECORD_HEADER:]
    cut = at - RECORD_HEADER
    if not 0 < cut < len(payload):
        raise RelayError("the cut is outside the ClientHello")

    def record(part: bytes) -> bytes:
        return bytes([HANDSHAKE_RECORD]) + version + struct.pack(">H", len(part)) + part

    return record(payload[:cut]) + record(payload[cut:])


async def read_hello(reader: asyncio.StreamReader) -> bytes:
    """The first whole TLS record of the client, header included."""
    header = await asyncio.wait_for(reader.readexactly(RECORD_HEADER), HELLO_TIMEOUT)
    length = _u16(header, 3)
    if length > MAX_HELLO_BYTES:
        raise RelayError(f"the first TLS record is {length} bytes, more than {MAX_HELLO_BYTES}")
    return header + await asyncio.wait_for(reader.readexactly(length), HELLO_TIMEOUT)


async def resolve_host(host: str) -> tuple[str, int]:
    """The real address of a name, asked of the resolver of this container."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, RELAY_PORT, family=socket.AF_INET, type=socket.SOCK_STREAM)
    if not infos:
        raise RelayError(f"{host} resolves to no IPv4 address")
    address, port = infos[0][4][0], infos[0][4][1]
    return str(address), int(port)


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        writer.close()


@dataclass
class Relay:
    """Forwards the TLS of the blocked zone, cutting the ClientHello of the names that need it."""

    resolve: Resolve = resolve_host
    zone: str = DEFAULT_ZONE
    log: Callable[[str], None] = _to_stderr
    # name → whether its ClientHello has to be cut; filled by the first connection of that name
    split: dict[str, bool] = field(default_factory=dict)

    def serves(self, host: str) -> bool:
        return host == self.zone or host.endswith(f".{self.zone}")

    async def _open(
        self, host: str, hello: bytes, cut: int, split: bool
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter, bytes]:
        """Connect, send the ClientHello (split or as it is) and wait for the first answer."""
        address, port = await self.resolve(host)
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(address, port), CONNECT_TIMEOUT
        )
        try:
            writer.write(split_hello(hello, cut) if split else hello)
            await writer.drain()
            answer = await asyncio.wait_for(reader.read(65536), HANDSHAKE_TIMEOUT)
            if not answer:
                raise RelayError("the server closed the connection on the ClientHello")
        except (TimeoutError, ConnectionError, RelayError):
            writer.close()
            raise
        return reader, writer, answer

    async def _upstream(
        self, host: str, hello: bytes, cut: int
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter, bytes]:
        """The upstream connection, in the way this name is known to need, learning it if new."""
        known = self.split.get(host)
        if known is not None:
            return await self._open(host, hello, cut, known)
        try:
            opened = await self._open(host, hello, cut, split=False)
        except (TimeoutError, ConnectionError, RelayError) as exc:
            self.log(f"{host}: no handshake as it is ({exc or type(exc).__name__}); cutting it")
            opened = await self._open(host, hello, cut, split=True)
            self.split[host] = True
            self.log(f"{host}: the cut ClientHello goes through")
            return opened
        self.split[host] = False
        self.log(f"{host}: the handshake goes through as it is")
        return opened

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            try:
                hello = await read_hello(reader)
            except asyncio.IncompleteReadError as exc:
                # nothing was said at all: a health check or a port scan, not worth a line
                if not exc.partial:
                    writer.close()
                    return
                raise
            host, at = server_name(hello)
            if not self.serves(host):
                raise RelayError(f"{host} is not in {self.zone}: the relay serves that zone only")
            # the cut goes inside the name: a filter comparing one record no longer sees it whole
            cut = at + max(1, len(host) // 2)
            upstream_reader, upstream_writer, answer = await self._upstream(host, hello, cut)
        except (
            RelayError,
            TimeoutError,
            ConnectionError,
            asyncio.IncompleteReadError,
            OSError,
        ) as exc:
            self.log(f"connection refused: {exc}")
            writer.close()
            return
        writer.write(answer)
        await writer.drain()
        await asyncio.gather(
            _pipe(reader, upstream_writer), _pipe(upstream_reader, writer), return_exceptions=True
        )


async def serve(relay: Relay, address: str = DEFAULT_ADDRESS, port: int = RELAY_PORT) -> None:
    server = await asyncio.start_server(relay.handle, address, port)
    relay.log(f"relaying TLS of {relay.zone} on {address}:{port}")
    async with server:
        await server.serve_forever()


def main() -> None:
    """``python -m vibedpn.relay``: the relay service of compose.yaml."""
    relay = Relay(zone=os.environ.get("VIBEDPN_RELAY_ZONE", DEFAULT_ZONE))
    address = os.environ.get("VIBEDPN_RELAY_ADDRESS", DEFAULT_ADDRESS)
    port = int(os.environ.get("VIBEDPN_RELAY_PORT", RELAY_PORT))
    with contextlib.suppress(KeyboardInterrupt):  # the container stops it
        asyncio.run(serve(relay, address, port))


if __name__ == "__main__":
    main()
