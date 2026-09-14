"""Background round of routing.lists (docs/decisions.md, 21): every list stays fresh, and its
domains reach the resolver of smart. A list works from its last copy while its URL is down."""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import Awaitable, Callable

from vibedpn.config import Config
from vibedpn.engine.domainlists import (
    LIST_REFRESH_SECONDS,
    Fetch,
    ListCache,
    ListError,
    ListState,
    refresh_list,
)
from vibedpn.engine.resolver import Resolver

# A new list in config.yaml is fetched within this; a fresh one costs nothing per round.
LIST_CHECK_SECONDS = 10.0
# A list whose URL failed is asked again after this, not every round.
LIST_RETRY_SECONDS = 15 * 60.0

Sleep = Callable[[float], Awaitable[None]]


def _log(message: str) -> None:
    sys.stderr.write(f"vibedpn-core: {message}\n")


class ListsStatus:
    """The last state of every list by URL, read by request threads; replaced whole."""

    def __init__(self) -> None:
        self.states: dict[str, ListState] = {}


def list_due(state: ListState | None, attempted: float | None, now: float) -> bool:
    """Whether a list is asked this round: never asked, its copy aged, or its retry came."""
    if state is None:
        return True
    if state.error:
        return attempted is None or now - attempted >= LIST_RETRY_SECONDS
    return state.fetched_at is None or now - state.fetched_at >= LIST_REFRESH_SECONDS


async def watch_lists(
    current: Callable[[], Config],
    resolver: Resolver,
    cache: ListCache,
    fetch: Fetch,
    status: ListsStatus,
    *,
    sleep: Sleep = asyncio.sleep,
    every: float = LIST_CHECK_SECONDS,
    clock: Callable[[], float] = time.time,
) -> None:
    attempted: dict[str, float] = {}
    while True:
        config = current()
        # the resolver holds the domains in use: a restarted round picks up where the last one was
        domains = dict(resolver.lists)
        urls = [item.url for item in config.routing.lists] if config.routing is not None else []
        states = {url: state for url, state in status.states.items() if url in urls}
        gone = [url for url in domains if url not in urls]
        for url in gone:
            del domains[url]
            attempted.pop(url, None)
        changed = bool(gone)
        for url in urls:
            previous = states.get(url)
            if not list_due(previous, attempted.get(url), clock()):
                continue
            attempted[url] = clock()
            try:
                got, state = await asyncio.to_thread(refresh_list, url, cache, fetch)
            except ListError as exc:
                got = domains.get(url, [])
                state = ListState(url, len(got), None, str(exc))
            if state.error and (previous is None or previous.error != state.error):
                _log(f"domain list {state.error}")
            states[url] = state
            if got != domains.get(url):
                domains[url] = got
                changed = True
        status.states = states
        if changed:
            await asyncio.to_thread(cache.prune, urls)
            resolver.set_lists(config, domains)
            total = sum(len(names) for names in domains.values())
            _log(f"domain lists: {total} domains from {len(domains)} lists in use")
        await sleep(every)
