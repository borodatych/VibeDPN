"""routing.mode smart in core: AdGuard's query log feeds the DNS journal of each device (the
sniffer) and the learner; what is learned goes to the resolver and to the store.

Runs in every mode on a box with AdGuard: the journal helps write rules before smart is on, and
what was learned is ready when it is switched on.
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from vibedpn.config import Config
from vibedpn.engine.learned import LearnedError, LearnedSource, LearnedStore
from vibedpn.engine.learning import Learned, Learner, Unlearned
from vibedpn.engine.querylog import (
    PAGE_LIMIT,
    LogRecord,
    QueryLogError,
    newer_than,
    parse_page,
)
from vibedpn.engine.resolver import Resolver

JOURNAL_PER_DEVICE = 300  # the sniffer shows the last queries of a device
QUERYLOG_SECONDS = 2.0
OLDER_PAGES = 5  # a burst larger than this many pages between two rounds is partly skipped

FetchPage = Callable[[str | None], object]  # older_than cursor → the JSON body of one page
Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class JournalEntry:
    time: float
    name: str
    qtype: str
    cached: bool
    addresses: list[str]
    channel: str  # the channel set the name is under, or "direct"
    learned_from: str | None  # the site this query taught the name to follow, if it did


@dataclass
class DnsJournal:
    """The last queries per device, in memory only (docs/decisions.md, 11)."""

    per_device: int = JOURNAL_PER_DEVICE
    _entries: dict[str, deque[JournalEntry]] = field(default_factory=dict)

    def add(self, client: str, entry: JournalEntry) -> None:
        self._entries.setdefault(client, deque(maxlen=self.per_device)).append(entry)

    def clients(self) -> list[str]:
        return sorted(self._entries)

    def entries(self, client: str, since: float = 0.0) -> list[JournalEntry]:
        return [entry for entry in self._entries.get(client, ()) if entry.time > since]


def rule_of(config: Config) -> Callable[[str], tuple[str, bool] | None]:
    """name → (the rule domain it is under, whether that rule learns)."""
    rules = config.routing.domains if config.routing is not None else []
    by_name = {name: (rule.domain, rule.learn) for rule in rules for name in rule.names()}

    def lookup(name: str) -> tuple[str, bool] | None:
        labels = name.lower().rstrip(".").split(".")
        for start in range(len(labels) - 1):
            found = by_name.get(".".join(labels[start:]))
            if found is not None:
                return found
        return None

    return lookup


@dataclass
class SmartLoop:
    """One round: new log records → journal, learner, resolver, store."""

    config_now: Callable[[], Config]
    resolver: Resolver
    store: LearnedStore
    journal: DnsJournal
    fetch_page: FetchPage
    clock: Callable[[], float] = time.time
    cursor: str | None = None
    _config: Config | None = None
    _learner: Learner | None = None
    _logged: str = ""

    def start(self) -> None:
        """Bring back what was learned before this start of core."""
        self._refresh()
        assert self._learner is not None
        for item in self.store.names():
            if self.resolver.learn(item.name, item.parent):
                self._learner.remember(item.name, item.parent)

    def round(self) -> list[Learned | Unlearned]:
        self._refresh()
        assert self._learner is not None
        changes: list[Learned | Unlearned] = []
        for record in self._new_records():
            # the channel the query took when it was answered, before this record teaches anything
            channel = self.resolver.index.match(record.event.name) or "direct"
            found = self._learner.observe(record.event)
            learned_from = None
            for change in found:
                if isinstance(change, Learned):
                    if self.resolver.learn(change.name, change.parent):
                        self.store.record(
                            change.name, change.parent, LearnedSource.TIME, self.clock()
                        )
                        learned_from = change.parent
                else:
                    self.resolver.unlearn(change.name)
                    self.store.remove(change.name)
            changes.extend(found)
            self.journal.add(
                record.event.client,
                JournalEntry(
                    record.event.time,
                    record.event.name.lower().rstrip("."),
                    record.qtype,
                    record.cached,
                    record.addresses,
                    channel,
                    learned_from,
                ),
            )
            self.cursor = record.stamp
        self._store_cnames()
        return changes

    def forget(self, name: str) -> bool:
        """The owner removed a learned name."""
        self._refresh()
        assert self._learner is not None
        self._learner.forget(name)
        self.resolver.unlearn(name)
        return self.store.remove(name)

    def _refresh(self) -> None:
        config = self.config_now()
        if config is not self._config:
            previous = self._learner
            self._config = config
            self._learner = Learner(rule_of(config))
            if previous is not None:
                self._learner.adopt(previous)

    def _new_records(self) -> list[LogRecord]:
        records = parse_page(self.fetch_page(None))
        pages = 1
        # a full page whose oldest record is still after the cursor: more is behind it
        while (
            self.cursor is not None
            and len(records) >= PAGE_LIMIT
            and pages < OLDER_PAGES
            and newer_than(records[-1:], self.cursor)
        ):
            records += parse_page(self.fetch_page(records[-1].stamp))
            pages += 1
        return newer_than(records, self.cursor)

    def _store_cnames(self) -> None:
        stored = {item.name for item in self.store.names()}
        lookup = rule_of(self.config_now())
        for target, site in self.resolver.cnames.items():
            rule = lookup(site)
            if target not in stored and rule is not None:
                self.store.record(target, rule[0], LearnedSource.CNAME, self.clock())


async def watch_querylog(
    loop: SmartLoop, sleep: Sleep = asyncio.sleep, every: float = QUERYLOG_SECONDS
) -> None:
    """The background task: a failed round is logged once per distinct message and retried."""
    try:
        await asyncio.to_thread(loop.start)
    except LearnedError as exc:
        sys.stderr.write(f"vibedpn-core: smart: {exc}\n")
    while True:
        try:
            changes = await asyncio.to_thread(loop.round)
        except (QueryLogError, LearnedError, OSError) as exc:
            message = f"{exc.__class__.__name__}: {exc}"
            if message != loop._logged:
                sys.stderr.write(f"vibedpn-core: smart: query log: {message}\n")
                loop._logged = message
        else:
            loop._logged = ""
            for change in changes:
                if isinstance(change, Learned):
                    sys.stderr.write(
                        f"vibedpn-core: smart: {change.name} follows {change.parent}\n"
                    )
                else:
                    sys.stderr.write(
                        f"vibedpn-core: smart: {change.name} is generic, goes direct\n"
                    )
        await sleep(every)
