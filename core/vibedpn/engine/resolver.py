"""The resolver of core for routing.mode smart (docs/decisions.md, 11 and 17).

AdGuard asks it every name; it asks the DoH upstreams of ``dns.upstreams`` and, before answering,
puts the IPv4 addresses of a name under a domain rule (or learned for one) into the nft set of that
rule's channel. The TTL of those answers is capped, and the set element lives a margin longer than
the TTL, so AdGuard never serves from its cache an address the set has already forgotten.

Which device asked is not known here (AdGuard asks from its own address): the per-device journal
comes from AdGuard's query log. The last answers stay in memory to fill a set again at once:
after a CDN is learned, and after the router rebuilt its table (which empties the sets).

`nft add element` on an element that exists keeps its old timeout
(docs/knowledge/linux/nftables.md): a set is filled by one transaction of add, delete and add,
so the address never leaves the set.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from ipaddress import IPv4Address, IPv4Network

import dns.exception
import dns.message
import dns.query
import dns.rcode
import dns.rdatatype
import httpx

from vibedpn.config import Config, DomainChannel, DomainVia
from vibedpn.detect import find_tool

RESOLVER_HOST = "127.0.0.1"
RESOLVER_PORT = 5354  # AdGuard's upstream in routing.mode smart
ROUTER_FAMILY_TABLE = ("inet", "vibedpn_router")
MAX_ANSWER_TTL = 300  # seconds: a name under a rule is asked again at least this often
SET_MARGIN_SECONDS = 60  # a set element outlives the TTL AdGuard caches the answer for
RECENT_ANSWERS = 4096
UPSTREAM_TIMEOUT_SECONDS = 5.0
DIRECT_SET = "smart_direct"


# "This network" (RFC 1122): no packet is addressed there; ipaddress marks only 0.0.0.0 unspecified.
THIS_NETWORK = IPv4Network("0.0.0.0/8")


class ResolverError(RuntimeError):
    """A user-facing reason why a name could not be resolved or its set not filled."""


def channel_set(channel: DomainChannel) -> str:
    """The nft set of a channel: smart_direct, smart_vps, smart_dpn_<country|any>, smart_wg_<name>.

    A name of upstreams.wg may carry '-', which a set name spelled this way does not: it becomes
    '_', and a name never holds '_' itself, so two exits never share a set. Set names this long are
    accepted by the kernels the box runs on (knowledge linux/nftables.md)."""
    if channel.via is DomainVia.DPN:
        return f"smart_dpn_{(channel.country or 'any').lower()}"
    if channel.via is DomainVia.WG:
        return f"smart_wg_{(channel.uplink or '').replace('-', '_')}"
    return DIRECT_SET if channel.via is DomainVia.DIRECT else f"smart_{channel.via.value}"


def smart_set_names(config: Config) -> list[str]:
    """Every channel set the rules of this box need, in a stable order."""
    channels = config.routing.channels() if config.routing is not None else []
    return sorted({channel_set(item) for item in channels})


class RuleIndex:
    """Domain suffix → channel set; the longest suffix wins, learned names sit beside the rules."""

    def __init__(self, entries: Iterable[tuple[str, str]] = ()) -> None:
        self._sets: dict[str, str] = {}
        for name, set_name in entries:
            self.add(name, set_name)

    @classmethod
    def from_config(cls, config: Config, lists: Mapping[str, list[str]] | None = None) -> RuleIndex:
        """The rules of config.yaml over the domains of its lists: a rule for the same name wins."""
        index = cls()
        if config.routing is None:
            return index
        fetched = lists or {}
        for item in config.routing.lists:
            set_name = channel_set(item)
            for name in fetched.get(item.url, ()):
                index.add(name, set_name)
        for rule in config.routing.domains:
            for name in rule.names():
                index.add(name, channel_set(rule))
        return index

    def add(self, name: str, set_name: str) -> None:
        self._sets[name.lower().rstrip(".")] = set_name

    def remove(self, name: str) -> None:
        self._sets.pop(name.lower().rstrip("."), None)

    def match(self, qname: str) -> str | None:
        labels = qname.lower().rstrip(".").split(".")
        for start in range(len(labels) - 1):
            found = self._sets.get(".".join(labels[start:]))
            if found is not None:
                return found
        return None


@dataclass(frozen=True)
class AnswerFacts:
    """What a response says about its question name: addresses, CNAME targets, lowest TTL."""

    addresses: list[str]
    cname_targets: list[str]
    ttl: int | None


def answer_facts(response: dns.message.Message) -> AnswerFacts:
    addresses: list[str] = []
    targets: list[str] = []
    ttls: list[int] = []
    for rrset in response.answer:
        ttls.append(rrset.ttl)
        if rrset.rdtype == dns.rdatatype.A:
            addresses.extend(item.address for item in rrset)
        elif rrset.rdtype == dns.rdatatype.CNAME:
            targets.extend(item.target.to_text().rstrip(".").lower() for item in rrset)
    return AnswerFacts(addresses, targets, min(ttls) if ttls else None)


def steerable(addresses: Iterable[str]) -> list[str]:
    """The answer addresses a channel set may take. An answer of 0.0.0.0, loopback, link-local,
    multicast or a reserved address is a sinkhole or a local service, never a destination an uplink
    carries (found on the box: kinozal.tv answered 127.0.0.1). Private and benchmark ranges stay:
    a VPS serves its own private network through the tunnel, and the stands use them."""
    kept = []
    for address in addresses:
        ip = IPv4Address(address)
        if not (
            ip.is_unspecified
            or ip in THIS_NETWORK
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
        ):
            kept.append(address)
    return kept


def cap_ttl(response: dns.message.Message, cap: int = MAX_ANSWER_TTL) -> int | None:
    """Lower every answer TTL above ``cap``; returns the lowest TTL left."""
    lowest: int | None = None
    for rrset in response.answer:
        rrset.ttl = min(rrset.ttl, cap)
        lowest = rrset.ttl if lowest is None else min(lowest, rrset.ttl)
    return lowest


def fill_script(set_name: str, addresses: list[str], timeout: int) -> str:
    """One nft transaction that puts ``addresses`` into the set with a fresh ``timeout``: the first
    add makes sure they exist, delete and add renew the timeout; applied whole or not at all."""
    family, table = ROUTER_FAMILY_TABLE
    target = f"element {family} {table} {set_name}"
    timed = ", ".join(f"{address} timeout {timeout}s" for address in addresses)
    plain = ", ".join(addresses)
    return (
        f"add {target} {{ {timed} }}\ndelete {target} {{ {plain} }}\nadd {target} {{ {timed} }}\n"
    )


Nft = Callable[[str], None]
Exchange = Callable[[dns.message.Message], dns.message.Message]


def run_nft(script: str) -> None:
    nft = find_tool("nft")
    if nft is None:
        raise ResolverError("nft not found (the core image installs nftables)")
    completed = subprocess.run(
        [nft, "-f", "-"], input=script, check=False, capture_output=True, text=True
    )
    if completed.returncode != 0:
        raise ResolverError(f"nft could not fill a smart set: {completed.stderr.strip()}")


def doh_exchange(upstreams: list[str], client: httpx.Client) -> Exchange:
    """Ask the DoH upstreams in order; the first answer wins."""

    def exchange(query: dns.message.Message) -> dns.message.Message:
        last = ""
        for url in upstreams:
            try:
                response: dns.message.Message = dns.query.https(
                    query, url, timeout=UPSTREAM_TIMEOUT_SECONDS, session=client
                )
                return response
            except (httpx.HTTPError, dns.exception.DNSException, OSError) as exc:
                last = f"{url}: {exc.__class__.__name__}"
        raise ResolverError(f"no DoH upstream answered ({last or 'no upstreams'})")

    return exchange


@dataclass
class Resolver:
    """Resolve, fill the channel set, remember; the I/O is passed in so the logic is testable."""

    index: RuleIndex
    exchange: Exchange
    nft: Nft = run_nft
    clock: Callable[[], float] = time.monotonic
    recent: OrderedDict[str, tuple[list[str], int, float]] = field(default_factory=OrderedDict)
    cnames: dict[str, str] = field(default_factory=dict)  # CNAME target → the name that led to it
    learned: dict[str, str] = field(default_factory=dict)  # CDN → the site it follows
    lists: dict[str, list[str]] = field(default_factory=dict)  # URL of routing.lists → its domains

    def resolve(self, query: dns.message.Message) -> dns.message.Message:
        if query.question and query.question[0].rdtype == dns.rdatatype.AAAA:
            qname = query.question[0].name.to_text().rstrip(".").lower()
            if self.index.match(qname) not in (None, DIRECT_SET):
                # the channel sets are IPv4: an IPv6 address of this site would leave around them
                return dns.message.make_response(query)
        response = self.exchange(query)
        if not query.question:
            return response
        qname = query.question[0].name.to_text().rstrip(".").lower()
        facts = answer_facts(response)
        self._remember(qname, facts)
        set_name = self.index.match(qname)
        if set_name is None:
            return response
        # a CDN behind a CNAME follows the site exactly: its name joins the rule of the site
        for target in facts.cname_targets:
            if self.index.match(target) is None:
                self.index.add(target, set_name)
                self.cnames[target] = qname
        ttl = cap_ttl(response)
        wanted = steerable(facts.addresses)
        if wanted and ttl is not None:
            self.nft(fill_script(set_name, wanted, ttl + SET_MARGIN_SECONDS))
        return response

    def lookup(self, name: str) -> list[str]:
        """The IPv4 addresses of ``name`` for core itself, asked the way AdGuard asks: through the
        DoH upstreams and into the channel set of the name's rule. A sinkhole or a local answer is
        no destination (``steerable``)."""
        query = dns.message.make_query(name, dns.rdatatype.A)
        return steerable(answer_facts(self.resolve(query)).addresses)

    def learn(self, name: str, parent: str) -> bool:
        """A CDN follows ``parent``: route it like the parent, and fill the set from what the
        resolver saw for it lately. ``False`` when the parent is under no rule."""
        set_name = self.index.match(parent)
        if set_name is None:
            return False
        self.index.add(name, set_name)
        self.learned[name] = parent
        self._fill(name, set_name)
        return True

    def unlearn(self, name: str) -> None:
        """A learned name is generic after all (or the owner removed it): it goes direct again.
        Its addresses leave the channel set when their timeout runs out."""
        if self.learned.pop(name, None) is not None:
            self.index.remove(name)

    def set_lists(self, config: Config, lists: Mapping[str, list[str]]) -> None:
        """New domains of routing.lists: rebuild the index with them and fill the sets again."""
        self.lists = dict(lists)
        self.reload(config)

    def reload(self, config: Config) -> None:
        """config.yaml changed (rules, mode) and the router rebuilt its table: take the new rules,
        keep what was learned for sites still under a rule, fill the sets again."""
        self.index = RuleIndex.from_config(config, self.lists)
        for target, site in self.cnames.items():
            set_name = self.index.match(site)
            if set_name is not None:
                self.index.add(target, set_name)
        for name, parent in list(self.learned.items()):
            set_name = self.index.match(parent)
            if set_name is None:
                del self.learned[name]
            else:
                self.index.add(name, set_name)
        self.replay()

    def replay(self) -> None:
        """Fill every set again from the last answers: the router rebuilt its table."""
        for name in list(self.recent):
            set_name = self.index.match(name)
            if set_name is not None:
                self._fill(name, set_name)

    def _remember(self, qname: str, facts: AnswerFacts) -> None:
        if not facts.addresses or facts.ttl is None:
            return
        ttl = min(facts.ttl, MAX_ANSWER_TTL)
        self.recent[qname] = (facts.addresses, ttl, self.clock() + ttl)
        self.recent.move_to_end(qname)
        while len(self.recent) > RECENT_ANSWERS:
            self.recent.popitem(last=False)

    def _fill(self, name: str, set_name: str) -> None:
        remembered = self.recent.get(name)
        if remembered is None:
            return
        addresses, _ttl, expires = remembered
        left = int(expires - self.clock())
        wanted = steerable(addresses)
        if left > 0 and wanted:
            self.nft(fill_script(set_name, wanted, left + SET_MARGIN_SECONDS))


class ResolverProtocol(asyncio.DatagramProtocol):
    """UDP on loopback for AdGuard; each query is resolved in a thread, errors answer SERVFAIL."""

    def __init__(self, resolver: Resolver) -> None:
        self.resolver = resolver
        self.transport: asyncio.DatagramTransport | None = None
        self.last_error = ""  # logged once per distinct failure

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        assert isinstance(transport, asyncio.DatagramTransport)
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str | object, int]) -> None:
        asyncio.get_running_loop().create_task(self._answer(data, addr))

    async def _answer(self, data: bytes, addr: tuple[str | object, int]) -> None:
        try:
            query = dns.message.from_wire(data)
        except dns.exception.DNSException:
            return
        try:
            response = await asyncio.to_thread(self.resolver.resolve, query)
        except Exception as exc:
            # an unanswered query makes AdGuard wait for its timeout; SERVFAIL answers at once
            message = f"{exc.__class__.__name__}: {exc}"
            if message != self.last_error:
                sys.stderr.write(f"vibedpn-core: resolver: {message}\n")
                self.last_error = message
            response = dns.message.make_response(query)
            response.set_rcode(dns.rcode.SERVFAIL)
        if self.transport is not None:
            self.transport.sendto(response.to_wire(), addr)


async def serve_resolver(resolver: Resolver) -> None:
    """The UDP endpoint on loopback for AdGuard; a port taken logs once and core keeps running
    (AdGuard answers through its fallback servers)."""
    loop = asyncio.get_running_loop()
    try:
        transport, _protocol = await loop.create_datagram_endpoint(
            lambda: ResolverProtocol(resolver), local_addr=(RESOLVER_HOST, RESOLVER_PORT)
        )
    except OSError as exc:
        sys.stderr.write(
            f"vibedpn-core: resolver cannot listen on {RESOLVER_HOST}:{RESOLVER_PORT}:"
            f" {exc.strerror}; smart mode has no domain sets\n"
        )
        return
    try:
        await asyncio.Future()
    finally:
        transport.close()
