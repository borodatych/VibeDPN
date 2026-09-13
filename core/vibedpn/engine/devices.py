"""LAN devices the box has seen: the neighbour table of the LAN interface, kept in SQLite.

A device appears in the table only when it talks to the box — as its gateway or its DNS — which
is exactly the set the router acts on. Names come from reverse DNS through the host resolver: in
sidecar mode the DHCP leases live on the ISP router, and home routers usually answer PTR for
them. Parsing is pure; reading the table, the lookup and the database are the side effects.
"""

from __future__ import annotations

import json
import socket
import sqlite3
import subprocess
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path

from vibedpn.config import normalize_mac
from vibedpn.engine.router import find_ip

DB_FILE = "devices.db"
SCHEMA_VERSION = 1
# Entries without a usable address: nothing answered, or not a neighbour at all
# (ip-neighbour(8): failed, incomplete, noarp, none).
SKIPPED_STATES = frozenset({"FAILED", "INCOMPLETE", "NOARP", "NONE"})
DB_TIMEOUT_SECONDS = 5.0

Resolve = Callable[[str], str | None]


class DeviceError(RuntimeError):
    """The neighbour table or the device store could not be read or written."""


@dataclass(frozen=True)
class Neighbour:
    mac: str
    ip: IPv4Address


@dataclass(frozen=True)
class SeenDevice:
    mac: str
    ip: IPv4Address
    hostname: str | None
    first_seen: float
    last_seen: float


def parse_neighbours(
    listing: str, subnet: IPv4Network, box_address: IPv4Address
) -> list[Neighbour]:
    """Devices from ``ip -j -4 neigh show dev <lan>``: a MAC, an address of the LAN that is not the
    box itself, and a state that means the neighbour answered."""
    try:
        entries = json.loads(listing or "[]")
    except json.JSONDecodeError as exc:
        raise DeviceError("ip -j neigh returned no JSON") from exc
    seen: dict[str, Neighbour] = {}
    for entry in entries:
        if not isinstance(entry, dict) or "lladdr" not in entry:
            continue
        if SKIPPED_STATES.intersection(entry.get("state", [])):
            continue
        try:
            address = IPv4Address(str(entry.get("dst")))
            mac = normalize_mac(str(entry["lladdr"]))
        except ValueError:
            continue
        if address not in subnet or address == box_address:
            continue
        seen[mac] = Neighbour(mac, address)
    return list(seen.values())


def read_neighbours(interface: str) -> str:
    ip = find_ip()
    if ip is None:
        raise DeviceError("ip not found (the core image installs iproute2)")
    try:
        completed = subprocess.run(
            [ip, "-j", "-4", "neigh", "show", "dev", interface],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise DeviceError(f"cannot run ip: {exc.strerror}") from exc
    if completed.returncode != 0:
        raise DeviceError(f"ip neigh show dev {interface} failed: {completed.stderr.strip()}")
    return completed.stdout


def reverse_name(address: str) -> str | None:
    """The PTR name of ``address`` through the host resolver, or ``None`` when there is none."""
    try:
        name = socket.gethostbyaddr(address)[0].rstrip(".")
    except OSError:
        return None
    return name if name and name != address else None


class DeviceStore:
    """One row per MAC: the last address, its reverse name, when it was first and last seen."""

    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            with closing(self._connect()) as db, db:
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version > SCHEMA_VERSION:
                    raise DeviceError(
                        f"{path} has schema version {version}, this VibeDPN knows {SCHEMA_VERSION}"
                    )
                db.execute(
                    "CREATE TABLE IF NOT EXISTS devices ("
                    " mac TEXT PRIMARY KEY, ip TEXT NOT NULL, hostname TEXT,"
                    " first_seen REAL NOT NULL, last_seen REAL NOT NULL)"
                )
                db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        except sqlite3.Error as exc:
            raise DeviceError(f"cannot open {path}: {exc}") from exc

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=DB_TIMEOUT_SECONDS)

    def record(self, neighbours: list[Neighbour], now: float, resolve: Resolve) -> list[str]:
        """Store what the table shows; returns the MACs seen for the first time. Names are looked
        up before the transaction — only for new devices and changed addresses — so a slow
        resolver never holds the database."""
        try:
            with closing(self._connect()) as db:
                known = {
                    mac: (ip, hostname)
                    for mac, ip, hostname in db.execute("SELECT mac, ip, hostname FROM devices")
                }
        except sqlite3.Error as exc:
            raise DeviceError(f"cannot read {self.path}: {exc}") from exc
        names: dict[str, str | None] = {}
        for neighbour in neighbours:
            previous = known.get(neighbour.mac)
            if previous is None or previous[0] != str(neighbour.ip):
                names[neighbour.mac] = resolve(str(neighbour.ip))
        new = [neighbour.mac for neighbour in neighbours if neighbour.mac not in known]
        try:
            with closing(self._connect()) as db, db:
                for neighbour in neighbours:
                    if neighbour.mac not in known:
                        db.execute(
                            "INSERT INTO devices (mac, ip, hostname, first_seen, last_seen)"
                            " VALUES (?, ?, ?, ?, ?)",
                            (neighbour.mac, str(neighbour.ip), names[neighbour.mac], now, now),
                        )
                    elif neighbour.mac in names:
                        db.execute(
                            "UPDATE devices SET ip = ?, hostname = ?, last_seen = ? WHERE mac = ?",
                            (str(neighbour.ip), names[neighbour.mac], now, neighbour.mac),
                        )
                    else:
                        db.execute(
                            "UPDATE devices SET last_seen = ? WHERE mac = ?", (now, neighbour.mac)
                        )
        except sqlite3.Error as exc:
            raise DeviceError(f"cannot write {self.path}: {exc}") from exc
        return new

    def devices(self) -> list[SeenDevice]:
        try:
            with closing(self._connect()) as db:
                rows = db.execute(
                    "SELECT mac, ip, hostname, first_seen, last_seen FROM devices ORDER BY ip"
                ).fetchall()
        except sqlite3.Error as exc:
            raise DeviceError(f"cannot read {self.path}: {exc}") from exc
        return [
            SeenDevice(mac, IPv4Address(ip), hostname, first_seen, last_seen)
            for mac, ip, hostname, first_seen, last_seen in rows
        ]
