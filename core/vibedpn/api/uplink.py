"""The uplink watchers: the table of an uplink in use points at a gateway only while one answers.

A stopped gateway container leaves the bridge behind, so its route never disappears by itself
and traffic would sink into ARP silence. Each watcher probes its gateway; the watchers together
point every table in use at the gateway that carries its traffic now: its own while it answers,
else the first answering uplink of routing.fallback (decision 32). With none, the table has no
gateway route: the last-resort route holds the traffic (``routing.failopen: false``) or the lookup
falls through to the main table (``failopen: true``) — exactly what the owner chose.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial

from vibedpn.api.background import supervised
from vibedpn.api.journal import Journal, ignore_event
from vibedpn.engine.events import Event, EventAction, EventKind
from vibedpn.engine.probe import ping
from vibedpn.engine.router import ExitPlan, RouterError, Uplink, exit_routes, set_exit_route

UPLINK_CHECK_SECONDS = 5.0
PROBE_TIMEOUT_SECONDS = 1.0

Probe = Callable[[str, float], bool]
# The state of one gateway handed to whoever routes: raises RouterError when a route did not change
Settle = Callable[[str, bool], None]
Sleep = Callable[[float], Awaitable[None]]
# (uplink in use, the uplink that carried its traffic, the one carrying it now); None: no gateway
Reroute = Callable[[str, str | None, str | None], None]


@dataclass(frozen=True)
class UplinkState:
    """The last round of a watcher: whether the gateway answered, when, and what went wrong."""

    alive: bool
    checked_at: float  # unix seconds
    error: str = ""


Report = Callable[[UplinkState], None]
Watch = Callable[[str, Uplink, Report], Awaitable[None]]


def _ignore(_state: UplinkState) -> None:
    return None


def _ignore_reroute(_key: str, _before: str | None, _now: str | None) -> None:
    return None


def _log(message: str) -> None:
    sys.stderr.write(f"vibedpn-core: {message}\n")


def own_route(uplink: Uplink) -> Settle:
    """Route the table of ``uplink`` through its own gateway only: a watcher with no chain."""

    def settle(_key: str, alive: bool) -> None:
        set_exit_route(uplink, uplink if alive else None)

    return settle


async def watch_uplink(
    upstream: str,
    uplink: Uplink,
    *,
    probe: Probe = ping,
    settle: Settle | None = None,
    sleep: Sleep = asyncio.sleep,
    check_seconds: float = UPLINK_CHECK_SECONDS,
    report: Report = _ignore,
    journal: Journal = ignore_event,
) -> None:
    """Probe the gateway forever and settle the routes on every round: ``ip route replace`` is
    idempotent, so a route removed behind the watcher's back (a recreated bridge, a manual flush)
    comes back on the next round. Only changes of state and new errors are logged."""
    gateway = uplink.gateway
    settle = settle or own_route(uplink)
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
            await asyncio.to_thread(settle, upstream, alive)
        except RouterError as exc:
            error = f"cannot update the routes of uplink {upstream}: {exc}"
            if error != logged_error:
                _log(error)
                logged_error = error
        if alive != logged_state:
            state = "answers" if alive else "does not answer"
            _log(f"uplink {upstream} gateway {gateway} {state}")
            action = EventAction.GATEWAY_ANSWERS if alive else EventAction.GATEWAY_SILENT
            journal(Event(time.time(), EventKind.UPLINK, upstream, action))
            logged_state = alive
        report(UplinkState(alive, time.time(), error))
        await sleep(check_seconds)


class UplinkWatchers:
    """One watcher per uplink of the plan, by key: the uplinks in use and the ones of the fallback
    chain. The set follows policy, rule and chain changes without a restart, and a key whose uplink
    changed (countries renumbered) gets a fresh watcher.

    Each round of a watcher settles the routes: the table of every uplink in use points at the
    gateway ``exit_routes`` picks. One lock serialises the rounds, so two watchers never route the
    same table at once. A table whose exit moved is logged, journaled when a fallback uplink is
    part of the move, and handed to ``reroute`` (AdGuard drops its connections of the old path).

    ``run`` owns the tasks on the event loop; ``sync`` may be called from a request thread and
    hands the new plan over to the loop. A watcher that raised starts again (``supervised``):
    a dead one would leave the route of its gateway to nobody."""

    def __init__(
        self,
        plan: ExitPlan,
        watch: Watch | None = None,
        journal: Journal = ignore_event,
        reroute: Reroute = _ignore_reroute,
        route: Callable[[Uplink, Uplink | None], None] = set_exit_route,
    ) -> None:
        self._wanted = plan
        self._plan = plan
        self._journal = journal
        self._reroute = reroute
        self._route = route
        self._watch: Watch = watch or (
            lambda key, uplink, report: watch_uplink(
                key, uplink, settle=self.settle, report=report, journal=journal
            )
        )
        self._tasks: dict[str, tuple[Uplink, asyncio.Task[None]]] = {}
        # Written by the watchers on the loop, read by request threads; each value is replaced
        # whole, never mutated.
        self._states: dict[str, UplinkState] = {}
        # Guarded by _lock: the gateway states the rounds reported, and the exit each table has
        self._lock = threading.Lock()
        self._alive: dict[str, bool] = {}
        self._exits: dict[str, str | None] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._resettle: asyncio.Future[None] | None = None

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._apply(self._wanted)
        try:
            await asyncio.Event().wait()
        finally:
            tasks = [task for _uplink, task in self._tasks.values()]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            # a run started again after a failure must not take these for running watchers
            self._tasks.clear()
            self._states.clear()
            with self._lock:
                self._alive.clear()
                self._exits.clear()

    def _apply(self, plan: ExitPlan) -> None:
        with self._lock:
            self._plan = plan
            for key in list(self._alive):
                if plan.uplinks.get(key) != self._uplink_of(key):
                    self._alive.pop(key)
            for key in list(self._exits):
                if key not in plan.routed:
                    self._exits.pop(key)  # the router flushed its table
        for key in list(self._tasks):
            if plan.uplinks.get(key) != self._tasks[key][0]:
                self._tasks.pop(key)[1].cancel()
                self._states.pop(key, None)
        for key, uplink in plan.uplinks.items():
            if key not in self._tasks:
                watch = partial(self._watch, key, uplink, self._reporter(key))
                task = asyncio.ensure_future(supervised(f"uplink {key} watcher", watch))
                self._tasks[key] = (uplink, task)
        # A new chain or a new set in use moves tables now, not at the next round of a watcher
        self._resettle = asyncio.ensure_future(asyncio.to_thread(self._settle_all))

    def _uplink_of(self, key: str) -> Uplink | None:
        task = self._tasks.get(key)
        return None if task is None else task[0]

    def _reporter(self, key: str) -> Report:
        def report(state: UplinkState) -> None:
            if key in self._tasks:
                self._states[key] = state

        return report

    def settle(self, key: str, alive: bool) -> None:
        """A round of the watcher of ``key``: record its gateway and route every table in use
        whose exit this changes; the table of ``key`` itself is routed again on every round."""
        with self._lock:
            if key not in self._plan.uplinks:
                return  # a watcher of an old plan, cancelled already
            self._alive[key] = alive
            self._route_tables(refresh=key)

    def _settle_all(self) -> None:
        with self._lock:
            try:
                self._route_tables(refresh=None)
            except RouterError as exc:
                _log(f"cannot update the routes of the uplinks: {exc}")

    def _route_tables(self, refresh: str | None) -> None:
        plan = self._plan
        wanted = exit_routes(plan.routed, plan.fallback, self._alive)
        errors: list[str] = []
        for key, through in wanted.items():
            if key != refresh and key in self._exits and self._exits[key] == through:
                continue
            # a table this run has not routed yet counts as on its own gateway
            before = self._exits.get(key, key)
            via = None if through is None else plan.uplinks[through]
            try:
                self._route(plan.uplinks[key], via)
            except RouterError as exc:
                errors.append(str(exc))
                continue
            self._exits[key] = through
            if before != through:
                self._moved(key, before, through)
        if errors:
            raise RouterError("; ".join(errors))

    def _moved(self, key: str, before: str | None, through: str | None) -> None:
        fate = "direct" if self._plan.failopen else "held"
        where = {"direct": "goes direct", "held": "is held (kill switch)"}[fate]
        _log(f"traffic of uplink {key} {'goes through ' + through if through else where}")
        # the gateway events of the watcher tell a table that loses or regains its own gateway;
        # a move to or from another uplink is news of its own
        if any(item not in (key, None) for item in (before, through)):
            detail: dict[str, int | float | str] = {"through": through or fate}
            self._journal(Event(time.time(), EventKind.UPLINK, key, EventAction.REROUTED, detail))
        self._reroute(key, before, through)

    def sync(self, plan: ExitPlan) -> None:
        self._wanted = plan
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._apply, plan)

    def watched(self) -> list[str]:
        return list(self._tasks)

    def wanted(self) -> list[str]:
        """The uplinks watched now, whether or not their watcher has started yet: read from any
        thread, the plan is replaced whole and never changed in place."""
        return list(self._wanted.uplinks)

    def states(self) -> dict[str, UplinkState]:
        """The last round of every watched uplink; an uplink not probed yet is absent."""
        return dict(self._states)
