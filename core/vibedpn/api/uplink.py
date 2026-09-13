"""The uplink watcher: the gateway route of the active uplink exists only while its container
answers.

A stopped gateway container leaves the bridge behind, so its route never disappears by itself
and traffic would sink into ARP silence. The watcher withdraws the route when the gateway goes
quiet: then the last-resort route holds the traffic (``routing.failopen: false``) or the lookup
falls through to the main table (``failopen: true``) — exactly what the owner chose.
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from vibedpn.config import Upstream
from vibedpn.engine.probe import ping
from vibedpn.engine.router import UPLINKS, RouterError, set_gateway_route

UPLINK_CHECK_SECONDS = 5.0
PROBE_TIMEOUT_SECONDS = 1.0

Probe = Callable[[str, float], bool]
Apply = Callable[[Upstream, bool], None]
Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class UplinkState:
    """The last round of a watcher: whether the gateway answered, when, and what went wrong."""

    alive: bool
    checked_at: float  # unix seconds
    error: str = ""


Report = Callable[[UplinkState], None]
Watch = Callable[[Upstream, Report], Awaitable[None]]


def _ignore(_state: UplinkState) -> None:
    return None


def _log(message: str) -> None:
    sys.stderr.write(f"vibedpn-core: {message}\n")


async def watch_uplink(
    upstream: Upstream,
    *,
    probe: Probe = ping,
    apply: Apply = set_gateway_route,
    sleep: Sleep = asyncio.sleep,
    check_seconds: float = UPLINK_CHECK_SECONDS,
    report: Report = _ignore,
) -> None:
    """Probe the gateway forever and set the route on every round: ``ip route replace`` is
    idempotent, so a route removed behind the watcher's back (a recreated bridge, a manual flush)
    comes back on the next round. Only changes of state and new errors are logged."""
    gateway = UPLINKS[upstream].gateway
    logged_state: bool | None = None
    logged_error = ""
    while True:
        error = ""
        try:
            alive = await asyncio.to_thread(probe, gateway, PROBE_TIMEOUT_SECONDS)
        except OSError as exc:
            # No raw socket (no CAP_NET_RAW): a broken setup, reported, and treated as a dead
            # gateway so the owner's failopen choice still decides.
            error = f"cannot probe uplink {upstream} gateway {gateway}: {exc.strerror or exc}"
            if error != logged_error:
                _log(error)
                logged_error = error
            alive = False
        try:
            await asyncio.to_thread(apply, upstream, alive)
        except RouterError as exc:
            error = f"cannot update the route of uplink {upstream}: {exc}"
            if error != logged_error:
                _log(error)
                logged_error = error
        else:
            if alive != logged_state:
                state = "answers; LAN traffic goes through it" if alive else "does not answer"
                _log(f"uplink {upstream} gateway {gateway} {state}")
                logged_state = alive
        report(UplinkState(alive, time.time(), error))
        await sleep(check_seconds)


def _watch_with_report(upstream: Upstream, report: Report) -> Awaitable[None]:
    return watch_uplink(upstream, report=report)


class UplinkWatchers:
    """One watcher per uplink in use; the set follows device policy changes without a restart.

    ``run`` owns the tasks on the event loop; ``sync`` may be called from a request thread and
    hands the new set over to the loop."""

    def __init__(
        self,
        uplinks: list[Upstream],
        watch: Watch | None = None,
    ) -> None:
        self._wanted = list(uplinks)
        self._watch: Watch = watch or (
            lambda upstream, report: watch_uplink(upstream, report=report)
        )
        self._tasks: dict[Upstream, asyncio.Task[None]] = {}
        # Written by the watchers on the loop, read by request threads; each value is replaced
        # whole, never mutated.
        self._states: dict[Upstream, UplinkState] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._apply(self._wanted)
        try:
            await asyncio.Event().wait()
        finally:
            tasks = list(self._tasks.values())
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def _apply(self, uplinks: list[Upstream]) -> None:
        for upstream in list(self._tasks):
            if upstream not in uplinks:
                self._tasks.pop(upstream).cancel()
                self._states.pop(upstream, None)
        for upstream in uplinks:
            if upstream not in self._tasks:
                self._tasks[upstream] = asyncio.ensure_future(
                    self._watch(upstream, self._reporter(upstream))
                )

    def _reporter(self, upstream: Upstream) -> Report:
        def report(state: UplinkState) -> None:
            if upstream in self._tasks:
                self._states[upstream] = state

        return report

    def sync(self, uplinks: list[Upstream]) -> None:
        self._wanted = list(uplinks)
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._apply, list(uplinks))

    def watched(self) -> list[Upstream]:
        return list(self._tasks)

    def states(self) -> dict[Upstream, UplinkState]:
        """The last round of every watched uplink; an uplink not probed yet is absent."""
        return dict(self._states)
