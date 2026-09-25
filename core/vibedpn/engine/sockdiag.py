"""TCP connections of the host, listed and closed through the kernel's socket diagnostics

A connection whose path changed under it is dead: its packets leave another way, with another source
The far end answers the first of them with a reset, and the request riding on it fails
Closed at once, it leaves its owner to open a new one on the new path at the next request

NETLINK_SOCK_DIAG lists sockets with the uid of their owner and closes one by its id, as `ss -K`
Closing needs CAP_NET_ADMIN and a kernel built with CONFIG_INET_DIAG_DESTROY
Debian kernels have it, the Raspberry Pi kernels do not
Structures: include/uapi/linux/inet_diag.h, sock_diag.h and netlink.h of the kernel
"""

from __future__ import annotations

import errno
import os
import socket
import struct
from collections.abc import Callable
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address, ip_address

NETLINK_SOCK_DIAG = 4
SOCK_DIAG_BY_FAMILY = 20
SOCK_DESTROY = 21
NLMSG_ERROR = 2
NLMSG_DONE = 3
NLM_F_REQUEST = 0x01
NLM_F_ACK = 0x04
NLM_F_DUMP = 0x300
TCP_ESTABLISHED = 1
TCP_SYN_SENT = 2
# A connection being opened along the old path is as doomed as an open one
OPEN_STATES = (1 << TCP_ESTABLISHED) | (1 << TCP_SYN_SENT)
ALL_STATES = 0xFFFFFFFF
RECEIVE_BYTES = 65536
TIMEOUT_SECONDS = 5.0
# AF_NETLINK exists only on Linux
AF_NETLINK = getattr(socket, "AF_NETLINK", None)

HEADER = struct.Struct("=IHHII")  # nlmsghdr: length, type, flags, seq, pid
REQUEST = struct.Struct("=BBBBI")  # inet_diag_req_v2 before its socket id
MESSAGE = struct.Struct("=BBBB")  # inet_diag_msg before its socket id
ADDRESSES = struct.Struct(">HH16s16s")  # ports and addresses, in network order
IDENTITY = struct.Struct("=III")  # interface and cookie, in host order
TAIL = struct.Struct("=IIIII")  # expires, rqueue, wqueue, uid, inode
ERROR = struct.Struct("=i")
SOCKET_ID_BYTES = ADDRESSES.size + IDENTITY.size
ADDRESS_BYTES = {socket.AF_INET: 4, socket.AF_INET6: 16}

Exchange = Callable[[bytes], list[tuple[int, bytes]]]


class SockDiagError(Exception):
    """The kernel refused to list or to close sockets"""


@dataclass(frozen=True)
class Connection:
    """A TCP socket as the kernel lists it
    socket_id is its id as the kernel gave it, cookie included: the only way to close exactly it
    """

    family: int
    local: IPv4Address | IPv6Address
    local_port: int
    peer: IPv4Address | IPv6Address
    peer_port: int
    uid: int
    socket_id: bytes


def message(kind: int, flags: int, body: bytes) -> bytes:
    return HEADER.pack(HEADER.size + len(body), kind, flags, 1, 0) + body


def parse_messages(data: bytes) -> list[tuple[int, bytes]]:
    """The netlink messages of one read: the type and the body of each"""
    messages = []
    offset = 0
    while offset + HEADER.size <= len(data):
        length, kind, _flags, _seq, _pid = HEADER.unpack_from(data, offset)
        if length < HEADER.size or offset + length > len(data):
            raise SockDiagError(f"the kernel answered a broken netlink message ({length} bytes)")
        messages.append((kind, data[offset + HEADER.size : offset + length]))
        offset += (length + 3) & ~3  # NLMSG_ALIGN
    return messages


def dump_request(family: int) -> bytes:
    """Ask for every open TCP socket of the family"""
    body = REQUEST.pack(family, socket.IPPROTO_TCP, 0, 0, OPEN_STATES) + bytes(SOCKET_ID_BYTES)
    return message(SOCK_DIAG_BY_FAMILY, NLM_F_REQUEST | NLM_F_DUMP, body)


def destroy_request(connection: Connection) -> bytes:
    """Close exactly this socket: the kernel finds it by the id it gave, cookie included"""
    body = REQUEST.pack(connection.family, socket.IPPROTO_TCP, 0, 0, ALL_STATES)
    return message(SOCK_DESTROY, NLM_F_REQUEST | NLM_F_ACK, body + connection.socket_id)


def parse_connection(body: bytes) -> Connection:
    family = MESSAGE.unpack_from(body)[0]
    width = ADDRESS_BYTES.get(family)
    if width is None or len(body) < MESSAGE.size + SOCKET_ID_BYTES + TAIL.size:
        raise SockDiagError(f"the kernel listed a socket of family {family} or of a short size")
    local_port, peer_port, local, peer = ADDRESSES.unpack_from(body, MESSAGE.size)
    uid = TAIL.unpack_from(body, MESSAGE.size + SOCKET_ID_BYTES)[3]
    return Connection(
        family=family,
        local=ip_address(local[:width]),
        local_port=local_port,
        peer=ip_address(peer[:width]),
        peer_port=peer_port,
        uid=uid,
        socket_id=body[MESSAGE.size : MESSAGE.size + SOCKET_ID_BYTES],
    )


def _failure(body: bytes) -> int:
    """The errno of an NLMSG_ERROR, 0 for an acknowledgement"""
    code: int = ERROR.unpack_from(body)[0]
    return -code


def netlink_exchange(request: bytes) -> list[tuple[int, bytes]]:
    """Send one request to the kernel and read its answer up to the end of a dump or the ack"""
    if AF_NETLINK is None:
        raise SockDiagError("this system has no netlink: sockets are listed on Linux only")
    try:
        with socket.socket(AF_NETLINK, socket.SOCK_RAW, NETLINK_SOCK_DIAG) as link:
            link.settimeout(TIMEOUT_SECONDS)
            link.sendto(request, (0, 0))
            answer: list[tuple[int, bytes]] = []
            while True:
                messages = parse_messages(link.recv(RECEIVE_BYTES))
                answer.extend(messages)
                if not messages or any(kind in (NLMSG_DONE, NLMSG_ERROR) for kind, _ in messages):
                    return answer
    except OSError as exc:
        raise SockDiagError(f"netlink: {exc.strerror or exc}") from exc


def list_connections(exchange: Exchange = netlink_exchange) -> list[Connection]:
    """Every open TCP connection of the host, IPv4 and IPv6"""
    connections = []
    for family in (socket.AF_INET, socket.AF_INET6):
        for kind, body in exchange(dump_request(family)):
            if kind == SOCK_DIAG_BY_FAMILY:
                connections.append(parse_connection(body))
            elif kind == NLMSG_ERROR and (code := _failure(body)):
                if family == socket.AF_INET6 and code == errno.EAFNOSUPPORT:
                    break  # a kernel without IPv6 has no IPv6 connection to list
                raise SockDiagError(f"the kernel does not list sockets: {os.strerror(code)}")
    return connections


def close_connection(connection: Connection, exchange: Exchange = netlink_exchange) -> bool:
    """Close one connection; False when it had closed on its own meanwhile"""
    for kind, body in exchange(destroy_request(connection)):
        if kind != NLMSG_ERROR:
            continue
        code = _failure(body)
        if code in (0, errno.ENOENT):
            return code == 0
        if code == errno.EOPNOTSUPP:
            raise SockDiagError(
                "the kernel cannot close sockets: it is built without CONFIG_INET_DIAG_DESTROY"
            )
        if code == errno.EPERM:
            raise SockDiagError("no right to close sockets: core runs without CAP_NET_ADMIN")
        raise SockDiagError(f"the kernel does not close a socket: {os.strerror(code)}")
    raise SockDiagError("the kernel did not answer the request to close a socket")


def close_where(
    uid: int, doomed: Callable[[Connection], bool], exchange: Exchange = netlink_exchange
) -> int:
    """Close the open TCP connections of the uid that doomed picks; how many closed"""
    return sum(
        close_connection(connection, exchange)
        for connection in list_connections(exchange)
        if connection.uid == uid and doomed(connection)
    )


def can_close(exchange: Exchange = netlink_exchange) -> bool:
    """Whether the kernel closes sockets at all

    Asked to close a socket that does not exist, it answers ENOENT when it can
    Built without CONFIG_INET_DIAG_DESTROY, it answers EOPNOTSUPP
    The lookup comes first, so the answer needs no CAP_NET_ADMIN
    """
    nobody = Connection(
        socket.AF_INET, IPv4Address(0), 0, IPv4Address(0), 0, 0, bytes(SOCKET_ID_BYTES)
    )
    for kind, body in exchange(destroy_request(nobody)):
        if kind == NLMSG_ERROR:
            return _failure(body) != errno.EOPNOTSUPP
    raise SockDiagError("the kernel did not answer the request to close a socket")
