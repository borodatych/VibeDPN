"""Autolearning of routing.mode smart: a CDN follows the site that called it.

The heuristic and its numbers: docs/decisions.md, 19.

The box sees no HTTP referer, only DNS: which device asked which name, when. A name the same
device asks within a short window after a site under a rule is a candidate CDN of that site.
Analytics, ads and telemetry are asked right after almost every site; a name seen after many
different sites is generic, not a CDN of one, and is never learned.

Pure logic: events in, learned pairs out. Reading AdGuard's query log and storing what was
learned are elsewhere.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

WINDOW_SECONDS = 10.0  # a CDN is asked within this after its site
GENERIC_PARENTS = 3  # seen after more different sites than this: generic, never learned


@dataclass(frozen=True)
class DnsEvent:
    """One query of the per-device journal."""

    client: str
    name: str
    time: float  # seconds, any monotonic origin shared by the events


@dataclass(frozen=True)
class Learned:
    name: str
    parent: str  # the rule domain (not the subdomain asked) the name follows


@dataclass(frozen=True)
class Unlearned:
    """A learned name turned out to follow many sites: generic, no longer a CDN of one."""

    name: str


# name → the rule domain it is under, or None; and whether that rule learns
RuleOf = Callable[[str], tuple[str, bool] | None]


@dataclass
class Learner:
    """Feed events in time order; ``observe`` returns what was learned or unlearned with it."""

    rule_of: RuleOf
    window: float = WINDOW_SECONDS
    generic_parents: int = GENERIC_PARENTS
    # per client: recent parents (rule domain, time) inside the window
    _parents: dict[str, deque[tuple[str, float]]] = field(default_factory=dict)
    # candidate name → the different rule domains it followed
    _seen_after: dict[str, set[str]] = field(default_factory=dict)
    _learned: dict[str, str] = field(default_factory=dict)
    _generic: set[str] = field(default_factory=set)

    def observe(self, event: DnsEvent) -> list[Learned | Unlearned]:
        name = event.name.lower().rstrip(".")
        recent = self._parents.setdefault(event.client, deque())
        while recent and event.time - recent[0][1] > self.window:
            recent.popleft()
        rule = self.rule_of(name)
        if rule is not None:
            domain, learns = rule
            if learns:
                recent.append((domain, event.time))
            return []
        if not recent or name in self._generic:
            return []
        parents = {domain for domain, _time in recent}
        followed = self._seen_after.setdefault(name, set())
        followed.update(parents)
        if len(followed) > self.generic_parents:
            # asked after many different sites: analytics or telemetry, not a CDN of one site
            self._generic.add(name)
            if self._learned.pop(name, None) is not None:
                return [Unlearned(name)]
            return []
        if name in self._learned or len(parents) != 1:
            return []  # known already, or ambiguous between two sites open at once
        parent = next(iter(parents))
        self._learned[name] = parent
        return [Learned(name, parent)]

    def forget(self, name: str) -> None:
        """The owner removed a learned name: it may be learned again only after new evidence."""
        self._learned.pop(name, None)
        self._seen_after.pop(name, None)
        self._generic.discard(name)

    def observe_all(self, events: Iterable[DnsEvent]) -> list[Learned | Unlearned]:
        found: list[Learned | Unlearned] = []
        for event in sorted(events, key=lambda item: item.time):
            found.extend(self.observe(event))
        return found
