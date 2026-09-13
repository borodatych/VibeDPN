"""Terminal table of the LAN devices core has seen (``vibedpn device list``)."""

from __future__ import annotations

from collections.abc import Sequence

from vibedpn.api.models import DeviceView
from vibedpn.tunnel_view import handshake_text

TABLE_HEADER = ("NAME", "ADDRESS", "MAC", "POLICY", "LAST SEEN")
NO_VALUE = "-"
NEVER_SEEN = "never seen"  # a policy in config.yaml for a device discovery has not met


def render_devices(devices: Sequence[DeviceView], now: float) -> list[str]:
    if not devices:
        return [
            "no LAN devices seen yet: a device appears once it uses the box as its gateway or DNS"
        ]
    rows = [
        (
            device.name or device.hostname or NO_VALUE,
            NO_VALUE if device.ip is None else str(device.ip),
            device.mac or NO_VALUE,
            device.policy or NO_VALUE,
            NEVER_SEEN
            if device.last_seen is None
            else handshake_text(int(device.last_seen.timestamp()), now),
        )
        for device in devices
    ]
    table = [TABLE_HEADER, *rows]
    widths = [max(len(row[column]) for row in table) for column in range(len(TABLE_HEADER))]
    return [
        "  ".join(cell.ljust(widths[column]) for column, cell in enumerate(row)).rstrip()
        for row in table
    ]
