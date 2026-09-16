"""The event journal and the Wi-Fi clients as lines of the terminal (the CLI speaks English).

Pure: core hands over codes and numbers, the phrase is built here, as the panel builds its own.
"""

from __future__ import annotations

import time

from vibedpn.api.models import EventView, WifiClientView

MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR


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


def event_text(event: EventView) -> str:
    subject = event.subject
    session = event.detail.get("session_seconds")
    phrases = {
        "client_connected": f"{subject} joined Wi-Fi",
        "client_disconnected": (
            f"{subject} left Wi-Fi after {duration_text(float(session))}"
            if session is not None
            else f"{subject} left Wi-Fi"
        ),
        "ap_enabled": f"access point on {subject} is up",
        "ap_disabled": f"access point on {subject} is down",
        "gateway_answers": f"uplink {subject}: the gateway answers",
        "gateway_silent": f"uplink {subject}: the gateway does not answer",
    }
    return phrases.get(event.action, f"{event.kind} {subject}: {event.action}")


def event_line(event: EventView) -> str:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(event.time))
    return f"{stamp}  {event.kind:<6} {event_text(event)}"


def client_line(client: WifiClientView) -> str:
    label = f"{client.name} ({client.mac})" if client.name else client.mac
    signal = f"{client.signal_dbm} dBm" if client.signal_dbm is not None else "signal unknown"
    return f"{label}  connected {duration_text(client.connected_seconds)}, {signal}"
