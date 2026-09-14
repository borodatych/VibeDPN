"""Background round of the Mysterium consumers: the one of uplink dpn and one per exit country of
the domain rules (docs/decisions.md, 20). While uplink dpn is enabled, every round brings each
consumer toward config.yaml and keeps its last state for ``/status``."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from vibedpn.bootstrap import MYST_CONSUMER_PASSPHRASE_FILE, country_passphrase_file
from vibedpn.config import Config, Upstream
from vibedpn.engine.consumer import (
    CONSUMER_TEQUILAPI,
    CONSUMER_TIMEOUT_SECONDS,
    ConsumerState,
    reconcile,
    tequilapi_url,
)
from vibedpn.engine.myst import TequilaClient
from vibedpn.engine.router import country_key, country_uplinks, used_uplinks

CONSUMER_SECONDS = 30.0

Sleep = Callable[[float], Awaitable[None]]
# One round over every consumer: uplink key (dpn, dpn-<cc>) -> its state.
Round = Callable[[Config], dict[str, ConsumerState]]


def _log(message: str) -> None:
    sys.stderr.write(f"vibedpn-core: {message}\n")


@dataclass(frozen=True)
class ConsumerTarget:
    """One consumer container and what config.yaml wants from it."""

    key: str  # the uplink key: dpn, dpn-<cc>
    tequilapi: str
    passphrase_file: str
    country: str | None
    wanted: bool  # some LAN traffic may leave through it
    repair: str  # what recreates a missing passphrase


def consumer_targets(config: Config) -> list[ConsumerTarget]:
    """The consumer of uplink dpn, then one per rule country in its numbering order."""
    used = used_uplinks(config)
    targets = [
        ConsumerTarget(
            Upstream.DPN.value,
            CONSUMER_TEQUILAPI,
            MYST_CONSUMER_PASSPHRASE_FILE,
            config.upstreams.dpn.country,
            Upstream.DPN.value in used,
            "run `vibedpn init --force`",
        )
    ]
    for country, uplink in country_uplinks(config).items():
        key = country_key(country)
        targets.append(
            ConsumerTarget(
                key,
                tequilapi_url(uplink.gateway),
                country_passphrase_file(country),
                country,
                key in used,
                "run `vibedpn restart`: it creates the passphrase of a new country",
            )
        )
    return targets


class ConsumerStatus:
    """The last round by uplink key, read by request threads; replaced whole, never mutated."""

    def __init__(self) -> None:
        self.states: dict[str, ConsumerState] = {}


def consumer_round(secrets_dir: Path) -> Round:
    def one(target: ConsumerTarget) -> ConsumerState:
        try:
            passphrase = (secrets_dir / target.passphrase_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            return ConsumerState(
                None,
                "Unknown",
                "Unknown",
                target.country,
                f"cannot read {target.passphrase_file}: {exc.strerror or exc}; {target.repair}",
            )
        client = TequilaClient(base_url=target.tequilapi, timeout=CONSUMER_TIMEOUT_SECONDS)
        try:
            return reconcile(client, passphrase, target.country, wanted=target.wanted)
        finally:
            client.close()

    def every(config: Config) -> dict[str, ConsumerState]:
        return {target.key: one(target) for target in consumer_targets(config)}

    return every


async def watch_consumer(
    current: Callable[[], Config],
    status: ConsumerStatus,
    step: Round,
    *,
    sleep: Sleep = asyncio.sleep,
    every: float = CONSUMER_SECONDS,
) -> None:
    logged: dict[str, str] = {}
    while True:
        config = current()
        if config.upstreams.dpn.enabled:
            states = await asyncio.to_thread(step, config)
            status.states = states
            lines = {
                key: f"{key} consumer: {state.registration}, {state.connection}"
                + (f" — {state.error}" if state.error else "")
                for key, state in states.items()
            }
            for key, line in lines.items():
                if logged.get(key) != line:
                    _log(line)
            logged = lines
        else:
            status.states = {}
        await sleep(every)
