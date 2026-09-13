"""Device discovery: the neighbour table of the LAN interface into the device store, every round.

In gateway mode the box hands out the addresses itself, so the DHCP leases of dnsmasq are a second
source: a device with a lease is listed before it ever talks through the box, and the name its DHCP
client sent wins over the PTR name (the box's own DNS knows no LAN names).

A failed round is logged once per distinct message and retried; discovery never stops the API.
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from vibedpn.config import Config, NetworkMode
from vibedpn.engine import dnsmasq
from vibedpn.engine.devices import (
    DeviceError,
    DeviceStore,
    Neighbour,
    Resolve,
    parse_leases,
    parse_neighbours,
    read_leases,
    read_neighbours,
    reverse_name,
)

DISCOVERY_SECONDS = 30.0

Read = Callable[[str], str]
ReadLeases = Callable[[Path], str]
Sleep = Callable[[float], Awaitable[None]]


def _log(message: str) -> None:
    sys.stderr.write(f"vibedpn-core: {message}\n")


async def watch_devices(
    config: Config,
    store: DeviceStore,
    *,
    read: Read = read_neighbours,
    read_lease_file: ReadLeases = read_leases,
    resolve: Resolve = reverse_name,
    sleep: Sleep = asyncio.sleep,
    every: float = DISCOVERY_SECONDS,
) -> None:
    network = config.network
    if network is None:
        return
    gateway = network.mode is NetworkMode.GATEWAY
    lease_file = dnsmasq.core_dir() / dnsmasq.LEASE_FILE
    logged = ""
    while True:
        try:
            now = time.time()
            listing = await asyncio.to_thread(read, network.lan_interface)
            neighbours = parse_neighbours(listing, network.lan_subnet, network.lan_address)
            named = resolve
            if gateway:
                text = await asyncio.to_thread(read_lease_file, lease_file)
                leases = parse_leases(text, network.lan_subnet, network.lan_address, now)
                # the lease is the address the box handed out: it wins over a stale neighbour entry
                merged = {n.mac: n for n in neighbours} | {
                    lease.mac: Neighbour(lease.mac, lease.ip) for lease in leases
                }
                neighbours = list(merged.values())
                names = {str(lease.ip): lease.hostname for lease in leases if lease.hostname}
                named = _lease_names_first(names, resolve)
            new = await asyncio.to_thread(store.record, neighbours, now, named)
        except DeviceError as exc:
            if str(exc) != logged:
                _log(f"device discovery: {exc}")
                logged = str(exc)
        else:
            logged = ""
            for mac in new:
                _log(f"new LAN device {mac}")
        await sleep(every)


def _lease_names_first(names: dict[str, str], resolve: Resolve) -> Resolve:
    def lookup(address: str) -> str | None:
        return names.get(address) or resolve(address)

    return lookup
