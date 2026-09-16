"""The Wi-Fi watcher: events of the access point into the journal, as hostapd reports them.

The watcher attaches to the control socket of hostapd and journals clients connecting and leaving
and the access point going up and down. The length of a session is measured from the connect it
saw, or from ``connected_time`` of the clients already there when it attached.

hostapd recreates its socket whenever it restarts, and a datagram socket connected to the old one
simply goes quiet. So a quiet spell is followed by ``PING``: no ``PONG`` means reconnect.
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import Awaitable, Callable

from vibedpn.api.journal import Journal
from vibedpn.config import Config
from vibedpn.engine.events import Detail, Event, EventAction, EventKind
from vibedpn.engine.wifi import (
    AP_DISABLED,
    AP_ENABLED,
    CLIENT_CONNECTED,
    CLIENT_DISCONNECTED,
    ApControl,
    ApEvent,
    HostapdControl,
    WifiError,
    parse_event,
)

QUIET_SECONDS = 30.0
RETRY_SECONDS = 10.0
ALIVE_REPLY = "PONG"

OpenControl = Callable[[str], ApControl]
Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]

ACTIONS = {
    CLIENT_CONNECTED: EventAction.CLIENT_CONNECTED,
    CLIENT_DISCONNECTED: EventAction.CLIENT_DISCONNECTED,
    AP_ENABLED: EventAction.AP_ENABLED,
    AP_DISABLED: EventAction.AP_DISABLED,
}


def _log(message: str) -> None:
    sys.stderr.write(f"vibedpn-core: {message}\n")


def to_event(ap_event: ApEvent, interface: str, now: float, sessions: dict[str, float]) -> Event:
    """The journal entry of an access point event; ``sessions`` (MAC -> connected at) follows it."""
    action = ACTIONS[ap_event.name]
    if ap_event.mac is None:
        if action is EventAction.AP_DISABLED:
            sessions.clear()
        return Event(now, EventKind.WIFI, interface, action)
    if action is EventAction.CLIENT_CONNECTED:
        sessions[ap_event.mac] = now
        return Event(now, EventKind.WIFI, ap_event.mac, action)
    started = sessions.pop(ap_event.mac, None)
    detail: Detail = {} if started is None else {"session_seconds": round(now - started)}
    return Event(now, EventKind.WIFI, ap_event.mac, action, detail)


async def watch_wifi(
    config: Config,
    journal: Journal,
    *,
    open_control: OpenControl = HostapdControl,
    sleep: Sleep = asyncio.sleep,
    clock: Clock = time.time,
    quiet: float = QUIET_SECONDS,
    retry: float = RETRY_SECONDS,
) -> None:
    network = config.network
    if network is None or network.wifi is None:
        return
    interface = network.lan_interface
    logged = ""
    while True:
        control: ApControl | None = None
        try:
            control = await asyncio.to_thread(open_control, interface)
            await asyncio.to_thread(control.attach)
            stations = await asyncio.to_thread(control.stations)
            now = clock()
            sessions = {station.mac: now - station.connected_seconds for station in stations}
            if logged:
                _log(f"Wi-Fi journal: attached to the access point on {interface} again")
            logged = ""
            while True:
                message = await asyncio.to_thread(control.receive, quiet)
                if message is None:
                    reply = await asyncio.to_thread(control.request, "PING")
                    if reply.strip() != ALIVE_REPLY:
                        raise WifiError("the access point stopped answering PING")
                    continue
                ap_event = parse_event(message)
                if ap_event is not None:
                    journal(to_event(ap_event, interface, clock(), sessions))
        except WifiError as exc:
            if str(exc) != logged:
                _log(f"Wi-Fi journal: {exc}; retrying every {retry:g} s")
                logged = str(exc)
        finally:
            if control is not None:
                control.close()
        await sleep(retry)
