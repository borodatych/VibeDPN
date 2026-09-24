"""Socket diagnostics: netlink messages as bytes, and which connections of AdGuard are closed."""

import errno
import socket
import struct
from ipaddress import ip_address

import pytest

from vibedpn.config import Config
from vibedpn.engine import sockdiag
from vibedpn.engine.adguard import close_upstream_connections
from vibedpn.engine.router import ADGUARD_UID
from vibedpn.engine.sockdiag import (
    NLMSG_DONE,
    NLMSG_ERROR,
    SOCK_DESTROY,
    SOCK_DIAG_BY_FAMILY,
    SockDiagError,
    close_connection,
    close_where,
    dump_request,
    list_connections,
    parse_connection,
    parse_messages,
)

from .conftest import client_config

COOKIE = (0x1234, 0x5678)


def listed(uid: int, local: str, local_port: int, peer: str, peer_port: int) -> bytes:
    """The body of an inet_diag_msg the kernel sends for one socket."""
    family = socket.AF_INET6 if ":" in local else socket.AF_INET
    head = struct.pack("=BBBB", family, 1, 0, 0)
    addresses = struct.pack(
        ">HH16s16s",
        local_port,
        peer_port,
        ip_address(local).packed.ljust(16, b"\0"),
        ip_address(peer).packed.ljust(16, b"\0"),
    )
    identity = struct.pack("=III", 0, *COOKIE)
    return head + addresses + identity + struct.pack("=IIIII", 0, 0, 0, uid, 42)


def framed(kind: int, body: bytes) -> bytes:
    """One netlink message as the kernel frames it, padded to four bytes."""
    length = 16 + len(body)
    return struct.pack("=IHHII", length, kind, 2, 1, 0) + body + b"\0" * (-length % 4)


def acknowledgement(code: int = 0) -> tuple[int, bytes]:
    return NLMSG_ERROR, struct.pack("=i", -code) + bytes(16)


class Kernel:
    """The netlink side of the tests: sockets to list, and what each request asked."""

    def __init__(self, v4: list[bytes], v6: list[bytes] | None = None, destroy: int = 0) -> None:
        self.listed: dict[int, list[bytes]] = {socket.AF_INET: v4, socket.AF_INET6: v6 or []}
        self.destroy = destroy
        self.destroyed: list[bytes] = []

    def __call__(self, request: bytes) -> list[tuple[int, bytes]]:
        kind = struct.unpack_from("=H", request, 4)[0]
        family = request[16]
        if kind == SOCK_DIAG_BY_FAMILY:
            return [(kind, body) for body in self.listed[family]] + [(NLMSG_DONE, b"\0" * 4)]
        assert kind == SOCK_DESTROY
        self.destroyed.append(request[24:])  # the socket id after the request header
        return [acknowledgement(self.destroy)]


def test_a_dump_asks_for_open_tcp_sockets_of_one_family() -> None:
    request = dump_request(socket.AF_INET)
    length, kind, flags = struct.unpack_from("=IHH", request)
    assert (length, kind, flags) == (72, SOCK_DIAG_BY_FAMILY, 0x301)  # 16 + 56 bytes, request|dump
    family, protocol, _ext, _pad, states = struct.unpack_from("=BBBBI", request, 16)
    assert (family, protocol, states) == (socket.AF_INET, socket.IPPROTO_TCP, 0b110)


def test_messages_are_split_on_their_padded_lengths() -> None:
    first = listed(ADGUARD_UID, "192.168.5.1", 45546, "162.159.61.8", 443)
    data = framed(SOCK_DIAG_BY_FAMILY, first) + framed(NLMSG_DONE, b"\0\0\0")
    assert parse_messages(data) == [(SOCK_DIAG_BY_FAMILY, first), (NLMSG_DONE, b"\0\0\0")]
    with pytest.raises(SockDiagError, match="broken netlink message"):
        parse_messages(data[:30])


def test_a_listed_socket_keeps_its_addresses_owner_and_id() -> None:
    connection = parse_connection(listed(ADGUARD_UID, "192.168.5.1", 45546, "162.159.61.8", 443))
    assert (connection.local, connection.local_port) == (ip_address("192.168.5.1"), 45546)
    assert (connection.peer, connection.peer_port) == (ip_address("162.159.61.8"), 443)
    assert connection.uid == ADGUARD_UID
    assert connection.socket_id[-8:] == struct.pack("=II", *COOKIE)  # the kernel's own cookie
    six = parse_connection(listed(ADGUARD_UID, "2001:db8::2", 40000, "2606:4700::6810:f8f9", 443))
    assert six.family == socket.AF_INET6 and six.peer == ip_address("2606:4700::6810:f8f9")


def test_close_where_closes_exactly_the_sockets_it_picked() -> None:
    kernel = Kernel(
        [
            listed(ADGUARD_UID, "192.168.5.1", 45546, "162.159.61.8", 443),
            listed(ADGUARD_UID, "192.168.1.50", 3000, "192.168.1.7", 51000),  # the LAN
            listed(0, "192.168.5.1", 50000, "162.159.61.8", 443),  # another user's
        ]
    )
    closed = close_where(ADGUARD_UID, lambda item: item.peer_port == 443, kernel)
    assert closed == 1
    assert kernel.destroyed == [
        listed(ADGUARD_UID, "192.168.5.1", 45546, "162.159.61.8", 443)[4:52]
    ]


def test_a_kernel_that_cannot_close_sockets_says_why() -> None:
    connection = parse_connection(listed(ADGUARD_UID, "192.168.5.1", 1, "1.1.1.1", 443))
    refusals = {
        errno.EOPNOTSUPP: "CONFIG_INET_DIAG_DESTROY",
        errno.EPERM: "CAP_NET_ADMIN",
        errno.EINVAL: "does not close",
    }
    for code, reason in refusals.items():
        with pytest.raises(SockDiagError, match=reason):
            close_connection(connection, Kernel([], destroy=code))
    assert close_connection(connection, Kernel([], destroy=errno.ENOENT)) is False  # gone already
    assert close_connection(connection, Kernel([])) is True


def test_a_kernel_without_ipv6_lists_ipv4_only() -> None:
    def exchange(request: bytes) -> list[tuple[int, bytes]]:
        if request[16] == socket.AF_INET6:
            return [acknowledgement(errno.EAFNOSUPPORT)]
        body = listed(ADGUARD_UID, "192.168.5.1", 1, "1.1.1.1", 443)
        return [(SOCK_DIAG_BY_FAMILY, body), (NLMSG_DONE, b"")]

    assert [item.peer for item in list_connections(exchange)] == [ip_address("1.1.1.1")]


def test_only_the_upstream_connections_of_adguard_are_closed() -> None:
    """The ones chain dns_uplink routes: not the LAN, not the box, and IPv6 to anything but lo."""
    doh = listed(ADGUARD_UID, "192.168.5.1", 45546, "162.159.61.8", 443)
    filter_list = listed(ADGUARD_UID, "192.168.5.1", 45600, "185.199.108.153", 443)
    doh6 = listed(ADGUARD_UID, "2001:db8::2", 40002, "2606:4700::6810:f8f9", 443)
    kernel = Kernel(
        [
            doh,
            filter_list,
            listed(ADGUARD_UID, "192.168.1.50", 3000, "192.168.1.7", 51000),  # the panel
            listed(ADGUARD_UID, "127.0.0.1", 40000, "127.0.0.1", 5353),  # core's resolver
            listed(ADGUARD_UID, "192.168.5.1", 40001, "192.168.5.1", 8080),  # the box itself
        ],
        [doh6, listed(ADGUARD_UID, "::1", 40003, "::1", 3000)],
    )
    assert close_upstream_connections(Config.model_validate(client_config()), kernel) == 3
    assert kernel.destroyed == [item[4:52] for item in (doh, filter_list, doh6)]


def test_a_box_without_adguard_closes_nothing() -> None:
    raw = client_config()
    raw["dns"] = {"enabled": False}
    kernel = Kernel([listed(ADGUARD_UID, "192.168.5.1", 1, "1.1.1.1", 443)])
    assert close_upstream_connections(Config.model_validate(raw), kernel) == 0
    assert kernel.destroyed == []


def test_without_netlink_nothing_is_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sockdiag, "AF_NETLINK", None)
    with pytest.raises(SockDiagError, match="Linux only"):
        list_connections()


def test_the_id_sent_to_close_is_the_one_the_kernel_listed() -> None:
    body = listed(ADGUARD_UID, "192.168.5.1", 45546, "162.159.61.8", 443)
    connection = parse_connection(body)
    request = sockdiag.destroy_request(connection)
    assert struct.unpack_from("=H", request, 4)[0] == SOCK_DESTROY
    assert request[24:] == body[4:52] == connection.socket_id
