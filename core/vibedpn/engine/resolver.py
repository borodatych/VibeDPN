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
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

import dns.exception
import dns.message
import dns.query
import dns.rcode
import dns.rdatatype
import httpx

from vibedpn.config import Config, DomainRule, DomainVia
from vibedpn.detect import find_tool

RESOLVER_HOST = "127.0.0.1"
RESOLVER_PORT = 5354  # AdGuard's upstream in routing.mode smart
ROUTER_FAMILY_TABLE = ("inet", "vibedpn_router")
MAX_ANSWER_TTL = 300  # seconds: a name under a rule is asked again at least this often
SET_MARGIN_SECONDS = 60  # a set element outlives the TTL AdGuard caches the answer for
RECENT_ANSWERS = 4096
UPSTREAM_TIMEOUT_SECONDS = 5.0


class ResolverError(RuntimeError):
    """A user-facing reason why a name could not be resolved or its set not filled."""


def channel_set(rule: DomainRule) -> str:
    """The nft set of a rule's channel: smart_direct, smart_vps, smart_dpn_<country|any>."""
    if rule.via is DomainVia.DPN:
        return f"smart_dpn_{(rule.country or 'any').lower()}"
    return f"smart_{rule.via.value}"


def smart_set_names(config: Config) -> list[str]:
    """Every channel set the rules of this box need, in a stable order."""
    rules = config.routing.domains if config.routing is not None else []
    return sorted({channel_set(rule) for rule in rules})


class RuleIndex:
    """Domain suffix → channel set; the longest suffix wins, learned names sit beside the rules."""

    def __init__(self, entries: Iterable[tuple[str, str]] = ()) -> None:
        self._sets: dict[str, str] = {}
        for name, set_name in entries:
            self.add(name, set_name)

    @classmethod
    def from_config(cls, config: Config) -> RuleIndex:
        rules = config.routing.domains if config.routing is not None else []
        return cls((name, channel_set(rule)) for rule in rules for name in rule.names())

    def add(self, name: str, set_name: str) -> None:
        self._sets[name.lower().rstrip(".")] = set_name

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

    def resolve(self, query: dns.message.Message) -> dns.message.Message:
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
        if facts.addresses and ttl is not None:
            self.nft(fill_script(set_name, facts.addresses, ttl + SET_MARGIN_SECONDS))
        return response

    def learn(self, name: str, parent: str) -> bool:
        """A CDN follows ``parent``: route it like the parent, and fill the set from what the
        resolver saw for it lately. ``False`` when the parent is under no rule."""
        set_name = self.index.match(parent)
        if set_name is None:
            return False
        self.index.add(name, set_name)
        self._fill(name, set_name)
        return True

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
        if left > 0:
            self.nft(fill_script(set_name, addresses, left + SET_MARGIN_SECONDS))


class ResolverProtocol(asyncio.DatagramProtocol):
    """UDP on loopback for AdGuard; each query is resolved in a thread, errors answer SERVFAIL."""

    def __init__(self, resolver: Resolver) -> None:
        self.resolver = resolver
        self.transport: asyncio.DatagramTransport | None = None

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
        except (ResolverError, dns.exception.DNSException):
            response = dns.message.make_response(query)
            response.set_rcode(dns.rcode.SERVFAIL)
        if self.transport is not None:
            self.transport.sendto(response.to_wire(), addr)
