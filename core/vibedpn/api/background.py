"""The background loops of core, each started again when it raises.

core runs its loops (the uplink watchers, ddns, the Telegram bot and the rest) as tasks it awaits
only at shutdown, so an exception would end a loop for good without a word: for an uplink watcher,
a gateway route nobody keeps any more. Every loop runs under ``supervised``: an unexpected
exception goes to the log as its class and place, never its text (it could quote a request, and a
request may carry a secret), and the loop starts again after a pause that doubles up to a bound.
A loop that returns has finished its work (a box without Wi-Fi has no Wi-Fi journal) and stays
finished.

A loop started again must not trust what its failed run left behind, and what happens once per
start of core does not belong in the loop.
"""

from __future__ import annotations

import asyncio
import sys
import time
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

FIRST_PAUSE_SECONDS = 5.0
LONGEST_PAUSE_SECONDS = 300.0
# A loop that ran this long before it raised is not failing in a row: its pause starts short again.
STEADY_SECONDS = 600.0
# The code of VibeDPN itself, told from the libraries it calls
PACKAGE_DIR = Path(__file__).resolve().parents[1]

Start = Callable[[], Awaitable[None]]
Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


@dataclass(frozen=True)
class BackgroundLoop:
    """A loop of core and the name the log calls it by."""

    name: str
    start: Start


def failure(exc: BaseException) -> str:
    """An unexpected exception as the log may show it: its class and place, never its text

    Raised inside a library, the place alone does not say which call of ours failed
    So the last line of our own code that led there follows it: `at decoder.py:355 from ddns.py:140`
    """
    frames = traceback.extract_tb(exc.__traceback__)
    if not frames:
        return exc.__class__.__name__
    raised = frames[-1]
    where = f"{exc.__class__.__name__} at {Path(raised.filename).name}:{raised.lineno}"
    ours = next((frame for frame in reversed(frames) if _ours(frame.filename)), None)
    if ours is None or ours is raised:
        return where
    return f"{where} from {Path(ours.filename).name}:{ours.lineno}"


def _ours(filename: str) -> bool:
    return Path(filename).resolve().is_relative_to(PACKAGE_DIR)


async def supervised(
    name: str, start: Start, *, sleep: Sleep = asyncio.sleep, clock: Clock = time.monotonic
) -> None:
    """Run the loop until it returns, starting it again after every exception. Cancelling goes
    through: ``CancelledError`` is not an ``Exception``."""
    pause = FIRST_PAUSE_SECONDS
    while True:
        started = clock()
        try:
            await start()
        except Exception as exc:
            if clock() - started >= STEADY_SECONDS:
                pause = FIRST_PAUSE_SECONDS
            sys.stderr.write(
                f"vibedpn-core: {name} failed: {failure(exc)}; it starts again in {pause:g} s\n"
            )
        else:
            return
        await sleep(pause)
        pause = min(pause * 2, LONGEST_PAUSE_SECONDS)
