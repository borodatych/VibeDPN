"""Writing into the event journal from the background loops: a failed write is logged once and
never stops the loop that noticed the event."""

from __future__ import annotations

import sys
from collections.abc import Callable

from vibedpn.engine.events import Event, EventError, EventStore

Journal = Callable[[Event], None]


def _log(message: str) -> None:
    sys.stderr.write(f"vibedpn-core: {message}\n")


def ignore_event(_event: Event) -> None:
    return None


def store_journal(store: EventStore) -> Journal:
    logged = ""

    def journal(event: Event) -> None:
        nonlocal logged
        try:
            store.add(event)
        except EventError as exc:
            if str(exc) != logged:
                _log(f"event journal: {exc}")
                logged = str(exc)
        else:
            logged = ""

    return journal
