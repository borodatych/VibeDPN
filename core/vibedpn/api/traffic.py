"""The traffic watchers: counters into totals that survive a restart.

Two sources, one store: the peers of a VPS (``wg show``) and the people of the access server (the
counters Xray publishes on loopback, ``/debug/vars``). Both count from the moment their process
came up, so core samples them and adds only what is new (engine/traffic.py), each into its own
database. Nothing here decides anything about a peer or a person — it records, and what to do with
a number is a question for whoever reads it.
"""

from __future__ import annotations

import asyncio
import sqlite3
import sys
import time
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path

import httpx

from vibedpn.engine.access import HEALTH_EMAIL, METRICS_PORT, list_people
from vibedpn.engine.traffic import Sample, connect, prune, record
from vibedpn.engine.wg import PeerLink, read_wg_dump

# A minute is far below anything a report asks about and far above the cost of reading a counter.
SAMPLE_SECONDS = 60.0
# Old days go once a day, not on every sample: the deletion has nothing to do in between.
PRUNE_EVERY = 24 * 60

# The totals of the access server live apart from the tunnel's: a person is not a peer.
ACCESS_TRAFFIC_DIR = "access-traffic"
METRICS_URL = f"http://127.0.0.1:{METRICS_PORT}/debug/vars"
METRICS_TIMEOUT_SECONDS = 5

Sleep = Callable[[float], Awaitable[None]]
Now = Callable[[], float]
ReadSamples = Callable[[], list[Sample] | None]


def samples_of(links: Mapping[str, PeerLink]) -> list[Sample]:
    return [Sample(key, link.rx_bytes, link.tx_bytes) for key, link in sorted(links.items())]


def wg_samples() -> list[Sample] | None:
    """The peers of the tunnel, by public key; ``None`` while the interface cannot be read."""
    links = read_wg_dump()
    return None if links is None else samples_of(links)


def access_samples(secrets_dir: Path, url: str = METRICS_URL) -> list[Sample] | None:
    """The people of the access server, by their id: what the server received from a person is
    their upload (``uplink``), what it sent them their download. ``None`` while the server does not
    answer. The service user of the health check is nobody's traffic."""
    try:
        response = httpx.get(url, timeout=METRICS_TIMEOUT_SECONDS, trust_env=False)
        users = response.json()["stats"]["user"] if response.is_success else None
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(users, dict):
        return None
    ids = {person.name: person.id for person in list_people(secrets_dir)}
    return [
        Sample(ids[email], int(counters.get("uplink", 0)), int(counters.get("downlink", 0)))
        for email, counters in sorted(users.items())
        if email != HEALTH_EMAIL and email in ids and isinstance(counters, dict)
    ]


async def watch_traffic(
    data_dir: Path,
    *,
    read: ReadSamples = wg_samples,
    sleep: Sleep = asyncio.sleep,
    now: Now = time.time,
    rounds: int | None = None,
) -> None:
    """Sample every ``SAMPLE_SECONDS`` while core runs; ``rounds`` bounds it for the tests.

    A failure to read the counters is not a failure of the watcher: the server may be restarting,
    and the next sample carries the traffic of this one — the totals are built from differences.
    """
    connection = connect(data_dir)
    try:
        round_number = 0
        while rounds is None or round_number < rounds:
            round_number += 1
            try:
                # off the event loop: core answers DNS on it, and a server that hangs must not
                # hold the house's names for the seconds its counters take to time out
                samples = await asyncio.to_thread(read)
                if samples:
                    record(connection, samples, now())
                if round_number % PRUNE_EVERY == 0:
                    prune(connection, now())
            except (OSError, sqlite3.Error) as exc:
                sys.stderr.write(f"vibedpn-core: traffic sample failed: {exc}\n")
            await sleep(SAMPLE_SECONDS)
    finally:
        connection.close()
