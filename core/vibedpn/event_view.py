"""The event journal and the Wi-Fi clients as lines of the terminal (the CLI speaks English).

Pure: core hands over codes and numbers, the phrase is built here, as the panel builds its own.
A device is always shown with its MAC, and by name when the box knows one: some devices never
tell their name.
"""

from __future__ import annotations

import time

from vibedpn.api.models import EventView, WifiClientView

MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR
UNKNOWN_DEVICE = "unknown"
CLIENT_ACTIONS = frozenset({"client_connected", "client_disconnected"})


def duration_text(seconds: float) -> str:
    """``3 d 4 h``, ``2 h 5 min``, ``7 min``, ``40 s``: the two largest units that matter."""
    whole = int(seconds)
    if whole >= DAY:
        return f"{whole // DAY} d {(whole % DAY) // HOUR} h"
    if whole >= HOUR:
        return f"{whole // HOUR} h {(whole % HOUR) // MINUTE} min"
    if whole >= MINUTE:
        return f"{whole // MINUTE} min"
    return f"{whole} s"


def device_label(name: str | None, mac: str) -> str:
    return f"{name or UNKNOWN_DEVICE} ({mac})"


def event_subject(event: EventView) -> str:
    """Who or what the event is about: a device by name and MAC, the access point, an uplink."""
    if event.action in CLIENT_ACTIONS:
        return device_label(event.name, event.subject)
    if event.kind == "uplink":
        return f"uplink {event.subject}"
    return f"access point {event.subject}"


def event_text(event: EventView) -> str:
    session = event.detail.get("session_seconds")
    phrases = {
        "client_connected": "joined Wi-Fi",
        "client_disconnected": (
            f"left Wi-Fi after {duration_text(float(session))} connected"
            if session is not None
            else "left Wi-Fi"
        ),
        "ap_enabled": "is up",
        "ap_disabled": "is down",
        "gateway_answers": "the gateway answers",
        "gateway_silent": "the gateway does not answer",
        "rerouted": _rerouted_text(event),
    }
    return phrases.get(event.action, event.action)


def _rerouted_text(event: EventView) -> str:
    through = str(event.detail.get("through", ""))
    if through == "direct":
        return "its traffic goes direct"
    if through == "held":
        return "its traffic is held (kill switch)"
    return f"its traffic goes through {through}"


def event_line(event: EventView) -> str:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(event.time))
    return f"{stamp}  {event.kind:<6} {event_subject(event)}  {event_text(event)}"


def client_line(client: WifiClientView) -> str:
    signal = f"{client.signal_dbm} dBm" if client.signal_dbm is not None else "signal unknown"
    label = device_label(client.name, client.mac)
    return f"{label}  connected {duration_text(client.connected_seconds)}, {signal}"
