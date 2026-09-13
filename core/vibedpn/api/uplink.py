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
from collections.abc import Awaitable, Callable

from vibedpn.config import Upstream
from vibedpn.engine.probe import ping
from vibedpn.engine.router import UPLINKS, RouterError, set_gateway_route

UPLINK_CHECK_SECONDS = 5.0
PROBE_TIMEOUT_SECONDS = 1.0

Probe = Callable[[str, float], bool]
Apply = Callable[[Upstream, bool], None]
Sleep = Callable[[float], Awaitable[None]]


def _log(message: str) -> None:
    sys.stderr.write(f"vibedpn-core: {message}\n")


async def watch_uplink(
    upstream: Upstream,
    *,
    probe: Probe = ping,
    apply: Apply = set_gateway_route,
    sleep: Sleep = asyncio.sleep,
    check_seconds: float = UPLINK_CHECK_SECONDS,
) -> None:
    """Probe the gateway forever and set the route on every round: ``ip route replace`` is
    idempotent, so a route removed behind the watcher's back (a recreated bridge, a manual flush)
    comes back on the next round. Only changes of state and new errors are logged."""
    gateway = UPLINKS[upstream].gateway
    logged_state: bool | None = None
    logged_error = ""
    while True:
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
        await sleep(check_seconds)
