"""The traffic watcher of a VPS: the counters of ``wg show`` into totals that survive a restart.

The interface counts from the moment it came up, so core samples it and adds only what is new
(engine/traffic.py). Nothing here decides anything about a peer — it records, and what to do with a
number is a question for whoever reads it.
"""

from __future__ import annotations

import asyncio
import sqlite3
import sys
import time
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path

from vibedpn.engine.traffic import Sample, connect, prune, record
from vibedpn.engine.wg import PeerLink, read_wg_dump

# A minute is far below anything a report asks about and far above the cost of reading a counter.
SAMPLE_SECONDS = 60.0
# Old days go once a day, not on every sample: the deletion has nothing to do in between.
PRUNE_EVERY = 24 * 60

Sleep = Callable[[float], Awaitable[None]]
Now = Callable[[], float]
ReadDump = Callable[[], Mapping[str, PeerLink] | None]


def samples_of(links: Mapping[str, PeerLink]) -> list[Sample]:
    return [Sample(key, link.rx_bytes, link.tx_bytes) for key, link in sorted(links.items())]


async def watch_traffic(
    data_dir: Path,
    *,
    read: ReadDump = read_wg_dump,
    sleep: Sleep = asyncio.sleep,
    now: Now = time.time,
    rounds: int | None = None,
) -> None:
    """Sample every ``SAMPLE_SECONDS`` while core runs; ``rounds`` bounds it for the tests.

    A failure to read the interface is not a failure of the watcher: wg-server may be restarting,
    and the next sample carries the traffic of this one — the totals are built from differences.
    """
    connection = connect(data_dir)
    try:
        round_number = 0
        while rounds is None or round_number < rounds:
            round_number += 1
            try:
                links = read()
                if links:
                    record(connection, samples_of(links), now())
                if round_number % PRUNE_EVERY == 0:
                    prune(connection, now())
            except (OSError, sqlite3.Error) as exc:
                sys.stderr.write(f"vibedpn-core: traffic sample failed: {exc}\n")
            await sleep(SAMPLE_SECONDS)
    finally:
        connection.close()
