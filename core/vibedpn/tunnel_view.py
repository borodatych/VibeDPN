"""How ``vibedpn peer`` prints peers: a table and a QR code. Pure text, tested without a box."""

from __future__ import annotations

import io
from collections.abc import Sequence

import segno

from vibedpn.api.models import PeerTraffic, PeerView
from vibedpn.engine.myst import human_bytes

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400
UNKNOWN = "?"
TABLE_HEADER = ("NAME", "ADDRESS", "ROUTES", "HANDSHAKE", "RX", "TX", "ENDPOINT")


def handshake_text(latest: int | None, now: float) -> str:
    """``None`` — core could not read the interface; 0 — the box never connected."""
    if latest is None:
        return UNKNOWN
    if latest == 0:
        return "never"
    age = max(0, int(now) - latest)
    if age < SECONDS_PER_MINUTE:
        return f"{age}s ago"
    if age < SECONDS_PER_HOUR:
        return f"{age // SECONDS_PER_MINUTE}m ago"
    if age < SECONDS_PER_DAY:
        return f"{age // SECONDS_PER_HOUR}h ago"
    return f"{age // SECONDS_PER_DAY}d ago"


def _bytes(count: int | None) -> str:
    return UNKNOWN if count is None else human_bytes(count)


def render_peers(peers: Sequence[PeerView], now: float) -> list[str]:
    if not peers:
        return ["no peers yet (add a home box: vibedpn peer add <name>)"]
    rows = [
        (
            peer.name,
            str(peer.address),
            "tunnel" if peer.tunnel_only else "all",
            "pending" if peer.applied is False else handshake_text(peer.latest_handshake, now),
            _bytes(peer.rx_bytes),
            _bytes(peer.tx_bytes),
            peer.endpoint or "-",
        )
        for peer in peers
    ]
    table = [TABLE_HEADER, *rows]
    widths = [max(len(row[column]) for row in table) for column in range(len(TABLE_HEADER))]
    lines = [
        "  ".join(cell.ljust(widths[column]) for column, cell in enumerate(row)).rstrip()
        for row in table
    ]
    if all(peer.applied is None for peer in peers):
        lines.append("live state unavailable: core cannot read wg0 (is wg-server running?)")
    return lines


def qr_code(text: str) -> str:
    """The peer file as a terminal QR code in Unicode half blocks, for a WireGuard app to scan."""
    buffer = io.StringIO()
    segno.make(text, micro=False).terminal(out=buffer, compact=True)
    return buffer.getvalue()


TRAFFIC_HEADER = ("PEER", "RECEIVED", "SENT", "TOTAL")


def render_peer_traffic(totals: Sequence[PeerTraffic], since: str | None) -> list[str]:
    """The traffic table, busiest peer first; a peer that was removed keeps its key as its name."""
    if not totals:
        return ["no traffic counted yet (core samples the tunnel once a minute)"]
    rows = [
        (
            item.name or f"(gone) {item.public_key[:12]}…",
            _bytes(item.rx_bytes),
            _bytes(item.tx_bytes),
            _bytes(item.rx_bytes + item.tx_bytes),
        )
        for item in totals
    ]
    table = [TRAFFIC_HEADER, *rows]
    widths = [max(len(row[column]) for row in table) for column in range(len(TRAFFIC_HEADER))]
    lines = [
        "  ".join(cell.ljust(widths[column]) for column, cell in enumerate(row)).rstrip()
        for row in table
    ]
    period = f" since {since}" if since else ""
    everything = sum(item.rx_bytes + item.tx_bytes for item in totals)
    return [*lines, f"total{period}: {_bytes(everything)}"]
