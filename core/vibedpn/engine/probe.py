"""Is an uplink gateway container alive? One ICMP echo over a raw socket.

core has no ``ping`` in its image and runs as root with Docker's default ``CAP_NET_RAW``. The
gateway containers answer echo requests even with their kill switch up: the reply is conntrack
``established``, which their output chain accepts. Packet building and parsing are pure; only
``ping`` touches the network.
"""

from __future__ import annotations

import os
import socket
import struct
import time

ICMP_ECHO_REQUEST = 8
ICMP_ECHO_REPLY = 0
IPV4_HEADER_LENGTH_MASK = 0x0F
IPV4_WORD_BYTES = 4
ICMP_HEADER = struct.Struct("!BBHHH")
PAYLOAD = b"vibedpn-uplink"
RECEIVE_BYTES = 1024


def checksum(data: bytes) -> int:
    """The Internet checksum (RFC 1071) of ``data``."""
    if len(data) % 2:
        data += b"\x00"
    total = int(sum(struct.unpack(f"!{len(data) // 2}H", data)))
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def echo_request(ident: int, sequence: int) -> bytes:
    header = ICMP_HEADER.pack(ICMP_ECHO_REQUEST, 0, 0, ident, sequence)
    return (
        ICMP_HEADER.pack(ICMP_ECHO_REQUEST, 0, checksum(header + PAYLOAD), ident, sequence)
        + PAYLOAD
    )


def is_echo_reply(packet: bytes, ident: int, sequence: int) -> bool:
    """A raw IPv4 socket returns the IP header too; skip it by its IHL field."""
    if not packet:
        return False
    offset = (packet[0] & IPV4_HEADER_LENGTH_MASK) * IPV4_WORD_BYTES
    if len(packet) < offset + ICMP_HEADER.size:
        return False
    kind, _, _, reply_ident, reply_sequence = ICMP_HEADER.unpack_from(packet, offset)
    return bool(kind == ICMP_ECHO_REPLY and reply_ident == ident and reply_sequence == sequence)


def ping(address: str, timeout: float) -> bool:
    """``True`` when ``address`` answers one echo request within ``timeout`` seconds.

    Raises ``OSError`` when the raw socket cannot be opened at all (no ``CAP_NET_RAW``): that
    is a broken setup, not a dead gateway, and the caller must say so."""
    ident = os.getpid() & 0xFFFF
    sequence = int(time.monotonic() * 1000) & 0xFFFF
    deadline = time.monotonic() + timeout
    with socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP) as sock:
        sock.sendto(echo_request(ident, sequence), (address, 0))
        while (left := deadline - time.monotonic()) > 0:
            sock.settimeout(left)
            try:
                packet, (source, _) = sock.recvfrom(RECEIVE_BYTES)
            except TimeoutError:
                return False
            if source == address and is_echo_reply(packet, ident, sequence):
                return True
    return False
