"""Background round of the dpn consumer: while uplink dpn is enabled, bring the consumer toward
config.yaml every round and keep its last state for ``/status``."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

from vibedpn.bootstrap import MYST_CONSUMER_PASSPHRASE_FILE
from vibedpn.config import Config, Upstream
from vibedpn.engine.consumer import (
    CONSUMER_TEQUILAPI,
    CONSUMER_TIMEOUT_SECONDS,
    ConsumerState,
    reconcile,
)
from vibedpn.engine.myst import TequilaClient
from vibedpn.engine.router import used_uplinks

CONSUMER_SECONDS = 30.0

Sleep = Callable[[float], Awaitable[None]]
Round = Callable[[Config], ConsumerState]


def _log(message: str) -> None:
    sys.stderr.write(f"vibedpn-core: {message}\n")


class ConsumerStatus:
    """The last round, read by request threads; replaced whole, never mutated."""

    def __init__(self) -> None:
        self.state: ConsumerState | None = None


def consumer_round(secrets_dir: Path) -> Round:
    def one(config: Config) -> ConsumerState:
        passphrase_path = secrets_dir / MYST_CONSUMER_PASSPHRASE_FILE
        try:
            passphrase = passphrase_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            return ConsumerState(
                None,
                "Unknown",
                "Unknown",
                config.upstreams.dpn.country,
                f"cannot read {MYST_CONSUMER_PASSPHRASE_FILE}: {exc.strerror or exc};"
                " run `vibedpn init --force`",
            )
        client = TequilaClient(base_url=CONSUMER_TEQUILAPI, timeout=CONSUMER_TIMEOUT_SECONDS)
        try:
            return reconcile(
                client,
                passphrase,
                config.upstreams.dpn.country,
                wanted=Upstream.DPN in used_uplinks(config),
            )
        finally:
            client.close()

    return one


async def watch_consumer(
    current: Callable[[], Config],
    status: ConsumerStatus,
    step: Round,
    *,
    sleep: Sleep = asyncio.sleep,
    every: float = CONSUMER_SECONDS,
) -> None:
    logged = ""
    while True:
        config = current()
        if config.upstreams.dpn.enabled:
            state = await asyncio.to_thread(step, config)
            status.state = state
            line = f"dpn consumer: {state.registration}, {state.connection}" + (
                f" — {state.error}" if state.error else ""
            )
            if line != logged:
                _log(line)
                logged = line
        else:
            status.state = None
        await sleep(every)
