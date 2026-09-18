"""The SNI relay: reading the server name, cutting the ClientHello, learning what a name needs."""

import asyncio
import ssl

import pytest

from vibedpn import relay as relay_module
from vibedpn.relay import (
    RECORD_HEADER,
    Relay,
    RelayError,
    read_hello,
    reason,
    server_name,
    split_hello,
)

HOST = "observer.mysterium.network"


def client_hello(host: str = HOST) -> bytes:
    """A real ClientHello of this Python, as a node would send it."""
    context = ssl.create_default_context()
    incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
    tls = context.wrap_bio(incoming, outgoing, server_hostname=host)
    with pytest.raises(ssl.SSLWantReadError):
        tls.do_handshake()
    return outgoing.read()


def test_the_server_name_is_read_where_it_lies() -> None:
    hello = client_hello()
    host, at = server_name(hello)
    assert host == HOST
    assert hello[at : at + len(HOST)] == HOST.encode()


def test_a_record_without_a_name_or_of_another_kind_is_refused() -> None:
    with pytest.raises(RelayError, match="not a TLS handshake record"):
        server_name(b"\x17\x03\x03\x00\x05hello")
    with pytest.raises(RelayError, match="names no server"):
        server_name(client_hello("192.0.2.10"))  # an address is sent without a server name


def test_the_cut_keeps_the_handshake_and_splits_the_name() -> None:
    hello = client_hello()
    host, at = server_name(hello)
    split = split_hello(hello, at + len(host) // 2)
    first_length = int.from_bytes(split[3:5], "big")
    second = split[RECORD_HEADER + first_length :]
    assert split[0] == hello[0] and second[0] == hello[0]
    # the two records carry exactly the bytes of the one record, in order
    assert (
        split[RECORD_HEADER : RECORD_HEADER + first_length] + second[RECORD_HEADER:]
        == hello[RECORD_HEADER:]
    )
    # neither record holds the whole name any more
    assert HOST.encode() not in split[: RECORD_HEADER + first_length]
    assert HOST.encode() not in second
    with pytest.raises(RelayError, match="outside the ClientHello"):
        split_hello(hello, RECORD_HEADER)


class FakeIsp:
    """An upstream that answers a ClientHello, unless one record carries the blocked name."""

    def __init__(self, blocked: str | None = HOST) -> None:
        self.blocked = blocked
        self.records: list[bytes] = []
        self.port = 0

    async def start(self) -> None:
        server = await asyncio.start_server(self.handle, "127.0.0.1", 0)
        self.port = server.sockets[0].getsockname()[1]
        self.server = server

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        record = await read_hello(reader)
        self.records.append(record)
        if self.blocked and self.blocked.encode() in record:
            # the filter swallows it: the client waits for a ServerHello that never comes
            writer.close()
            return
        # a real server reassembles a handshake spread over records; this one has to as well
        payload = record[RECORD_HEADER:]
        while len(payload) < 4 + int.from_bytes(payload[1:4], "big"):
            more = await read_hello(reader)
            self.records.append(more)
            payload += more[RECORD_HEADER:]
        writer.write(b"server-hello")
        await writer.drain()
        data = await reader.read(64)
        writer.write(b"echo:" + data)
        await writer.drain()
        writer.close()


async def talk(relay: Relay, isp: FakeIsp, host: str = HOST) -> bytes:
    server = await asyncio.start_server(relay.handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(client_hello(host))
    await writer.drain()
    answer = await reader.read(64)
    writer.write(b"payload")
    await writer.drain()
    rest = await reader.read(64)
    writer.close()
    server.close()
    return answer + rest


def relay_to(isp: FakeIsp, said: list[str] | None = None, **kwargs: object) -> Relay:
    async def resolve(_host: str) -> tuple[str, int]:
        return "127.0.0.1", isp.port

    lines = said if said is not None else []
    return Relay(resolve=resolve, log=lines.append, **kwargs)  # type: ignore[arg-type]


def test_a_blocked_name_goes_through_cut_and_the_choice_is_remembered() -> None:
    async def scenario() -> None:
        isp = FakeIsp()
        await isp.start()
        relay = relay_to(isp)
        assert await talk(relay, isp) == b"server-helloecho:payload"
        assert relay.routes == {HOST: relay_module.Route.SPLIT}
        # the ISP saw the whole name once (refused) and then never again
        assert sum(HOST.encode() in record for record in isp.records) == 1
        direct, first, second = isp.records
        assert first[RECORD_HEADER:] + second[RECORD_HEADER:] == direct[RECORD_HEADER:]
        await talk(relay, isp)
        # the remembered choice skips the direct attempt: two cut records, no third
        assert len(isp.records) == 5

    asyncio.run(scenario())


def test_a_name_that_is_not_blocked_is_forwarded_as_it_is() -> None:
    async def scenario() -> None:
        isp = FakeIsp(blocked=None)
        await isp.start()
        relay = relay_to(isp)
        assert await talk(relay, isp) == b"server-helloecho:payload"
        assert relay.routes == {HOST: relay_module.Route.AS_IS}
        # one record, the name whole inside it: nothing was cut
        assert len(isp.records) == 1 and HOST.encode() in isp.records[0]

    asyncio.run(scenario())


def test_a_name_outside_the_zone_is_refused() -> None:
    async def scenario() -> None:
        isp = FakeIsp(blocked=None)
        await isp.start()
        relay = relay_to(isp)
        assert await talk(relay, isp, host="example.com") == b""
        assert isp.records == [] and relay.routes == {}

    asyncio.run(scenario())


def test_a_caller_that_says_nothing_closes_without_a_word() -> None:
    """The healthcheck of the container opens the port and closes it: not a line every 30 s."""

    async def scenario() -> None:
        isp = FakeIsp(blocked=None)
        await isp.start()
        said: list[str] = []
        relay = relay_to(isp, said=said)
        server = await asyncio.start_server(relay.handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        _reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.close()
        await asyncio.sleep(0.05)
        server.close()
        assert said == [] and isp.records == []

    asyncio.run(scenario())


def test_the_log_names_a_failure_that_carries_no_text() -> None:
    """A timeout prints as an empty string: the log would then explain nothing."""
    assert reason(TimeoutError()) == "TimeoutError"
    assert (
        reason(RelayError("the server closed the connection")) == "the server closed the connection"
    )


class FakeSocks:
    """A SOCKS5 proxy standing in for Tor: it speaks the handshake and then carries the bytes to
    an upstream that no filter touches — which is what a circuit through Tor amounts to here."""

    def __init__(self, upstream_port: int, refuse: bool = False) -> None:
        self.upstream_port = upstream_port
        self.refuse = refuse
        self.asked: list[str] = []
        self.port = 0

    async def start(self) -> None:
        server = await asyncio.start_server(self.handle, "127.0.0.1", 0)
        self.port = server.sockets[0].getsockname()[1]
        self.server = server

    def address(self) -> str:
        return f"127.0.0.1:{self.port}"

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        greeting = await reader.readexactly(2)
        await reader.readexactly(greeting[1])  # the methods the client offers
        writer.write(bytes([5, 0]))
        await writer.drain()
        head = await reader.readexactly(4)
        size = (await reader.readexactly(1))[0]
        name = (await reader.readexactly(size)).decode()
        await reader.readexactly(2)  # port
        self.asked.append(name)
        if self.refuse or head[1] != 1:
            writer.write(bytes([5, 5, 0, 1, 0, 0, 0, 0, 0, 0]))  # connection refused
            await writer.drain()
            writer.close()
            return
        writer.write(bytes([5, 0, 0, 1, 127, 0, 0, 1, 0, 0]))
        await writer.drain()
        up_reader, up_writer = await asyncio.open_connection("127.0.0.1", self.upstream_port)
        await asyncio.gather(
            relay_module._pipe(reader, up_writer),
            relay_module._pipe(up_reader, writer),
            return_exceptions=True,
        )


def test_a_filtered_name_goes_through_tor_and_the_cut_stays_the_fallback() -> None:
    """Cutting the ClientHello only gets the handshake past the filter; the answer is throttled
    after it. So a name the ISP filters is carried through Tor whenever there is a proxy."""

    async def scenario() -> None:
        isp = FakeIsp()  # filters HOST: a direct ClientHello naming it stays unanswered
        await isp.start()
        free = FakeIsp(blocked=None)  # what the same server looks like from a Tor exit
        await free.start()
        socks = FakeSocks(free.port)
        await socks.start()
        said: list[str] = []
        relay = relay_to(isp, said, socks=socks.address())

        assert await talk(relay, isp) == b"server-helloecho:payload"
        assert relay.routes == {HOST: relay_module.Route.TOR}
        # the name travelled to the proxy, so it was resolved there and not on this box
        assert socks.asked == [HOST]
        # nothing was ever cut: the filtered name never had to be
        assert all(HOST.encode() in record for record in free.records)
        assert any("through Tor" in line for line in said)

        # the choice is remembered: the second connection goes straight through the proxy
        await talk(relay, isp)
        assert socks.asked == [HOST, HOST] and len(isp.records) == 1

    asyncio.run(scenario())


def test_a_refusing_proxy_leaves_the_cut_to_do_the_work() -> None:
    async def scenario() -> None:
        isp = FakeIsp()
        await isp.start()
        socks = FakeSocks(0, refuse=True)
        await socks.start()
        said: list[str] = []
        relay = relay_to(isp, said, socks=socks.address())

        assert await talk(relay, isp) == b"server-helloecho:payload"
        assert relay.routes == {HOST: relay_module.Route.SPLIT}
        assert any("does not get through either" in line for line in said)

    asyncio.run(scenario())


def test_the_socks_address_has_to_be_host_and_port() -> None:
    async def scenario() -> None:
        with pytest.raises(RelayError, match="SOCKS address"):
            await relay_module.open_through_socks("10.77.0.60", "example.org", 443)

    asyncio.run(scenario())
