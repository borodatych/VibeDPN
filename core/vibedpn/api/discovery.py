"""Device discovery: the neighbour table of the LAN interface into the device store, every round.

A failed round is logged once per distinct message and retried; discovery never stops the API.
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import Awaitable, Callable

from vibedpn.config import Config
from vibedpn.engine.devices import (
    DeviceError,
    DeviceStore,
    Resolve,
    parse_neighbours,
    read_neighbours,
    reverse_name,
)

DISCOVERY_SECONDS = 30.0

Read = Callable[[str], str]
Sleep = Callable[[float], Awaitable[None]]


def _log(message: str) -> None:
    sys.stderr.write(f"vibedpn-core: {message}\n")


async def watch_devices(
    config: Config,
    store: DeviceStore,
    *,
    read: Read = read_neighbours,
    resolve: Resolve = reverse_name,
    sleep: Sleep = asyncio.sleep,
    every: float = DISCOVERY_SECONDS,
) -> None:
    network = config.network
    if network is None:
        return
    logged = ""
    while True:
        try:
            listing = await asyncio.to_thread(read, network.lan_interface)
            neighbours = parse_neighbours(listing, network.lan_subnet, network.lan_address)
            new = await asyncio.to_thread(store.record, neighbours, time.time(), resolve)
        except DeviceError as exc:
            if str(exc) != logged:
                _log(f"device discovery: {exc}")
                logged = str(exc)
        else:
            logged = ""
            for mac in new:
                _log(f"new LAN device {mac}")
        await sleep(every)
