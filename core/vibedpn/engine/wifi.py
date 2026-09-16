"""The control interface of hostapd: events of the access point and its connected clients.

hostapd listens on a UNIX datagram socket ``<ctrl_interface>/<interface>`` (``ctrl_interface`` of
hostapd.conf). A client binds its own socket path, connects to that one, and sends text commands;
after ``ATTACH`` hostapd also sends unsolicited events, each starting with ``<level>``, such as
``<3>AP-STA-CONNECTED aa:bb:cc:dd:ee:ff`` (wpa_supplicant/hostapd control interface documentation
and src/common/wpa_ctrl.c, knowledge linux/hostapdControl.md).

Parsing is pure; the socket is the only side effect.
"""

from __future__ import annotations

import itertools
import os
import re
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from vibedpn.config import normalize_mac

CTRL_DIR_ENV = "VIBEDPN_HOSTAPD_CTRL"
DEFAULT_CTRL_DIR = Path("/run/vibedpn/hostapd")  # compose.yaml shares it with hostapd
CLIENT_PREFIX = "vibedpn-core-"
REPLY_BYTES = 8192
COMMAND_TIMEOUT_SECONDS = 3.0
ATTACHED = "OK"
NO_MORE_STATIONS = ("", "FAIL")

EVENT_LINE = re.compile(r"^<\d+>(?P<name>[A-Z0-9-]+)(?:\s+(?P<argument>\S+))?")
CLIENT_CONNECTED = "AP-STA-CONNECTED"
CLIENT_DISCONNECTED = "AP-STA-DISCONNECTED"
AP_ENABLED = "AP-ENABLED"
AP_DISABLED = "AP-DISABLED"
KNOWN_EVENTS = frozenset({CLIENT_CONNECTED, CLIENT_DISCONNECTED, AP_ENABLED, AP_DISABLED})

_counter = itertools.count()


class WifiError(RuntimeError):
    """The access point could not be asked: no socket, no answer, or an answer that is not one."""


@dataclass(frozen=True)
class ApEvent:
    name: str  # one of KNOWN_EVENTS
    mac: str | None  # the client of AP-STA-*; None for the access point itself


@dataclass(frozen=True)
class Station:
    mac: str
    connected_seconds: int
    signal_dbm: int | None
    inactive_ms: int | None
    rx_bytes: int | None
    tx_bytes: int | None


class ApControl(Protocol):
    """What the Wi-Fi watcher needs of a control connection; ``HostapdControl`` is the real one."""

    def attach(self) -> None: ...
    def stations(self) -> list[Station]: ...
    def receive(self, timeout: float) -> str | None: ...
    def request(self, command: str) -> str: ...
    def close(self) -> None: ...


def ctrl_dir() -> Path:
    return Path(os.environ.get(CTRL_DIR_ENV, DEFAULT_CTRL_DIR))


def parse_event(message: str) -> ApEvent | None:
    """An event this box journals, or ``None`` for anything else hostapd says."""
    match = EVENT_LINE.match(message.strip())
    if match is None or match["name"] not in KNOWN_EVENTS:
        return None
    if match["name"] in (CLIENT_CONNECTED, CLIENT_DISCONNECTED):
        try:
            return ApEvent(match["name"], normalize_mac(match["argument"] or ""))
        except ValueError:
            return None
    return ApEvent(match["name"], None)


def _number(fields: dict[str, str], key: str) -> int | None:
    try:
        return int(fields[key])
    except (KeyError, ValueError):
        return None


def parse_station(reply: str) -> Station | None:
    """The answer of ``STA-FIRST``/``STA-NEXT``: the MAC on the first line, then ``key=value``."""
    lines = reply.strip().splitlines()
    if not lines or lines[0].strip() in NO_MORE_STATIONS:
        return None
    try:
        mac = normalize_mac(lines[0].strip())
    except ValueError as exc:
        raise WifiError(f"hostapd answered something that is not a station: {lines[0]!r}") from exc
    fields = dict(line.split("=", 1) for line in lines[1:] if "=" in line)
    return Station(
        mac=mac,
        connected_seconds=_number(fields, "connected_time") or 0,
        signal_dbm=_number(fields, "signal"),
        inactive_ms=_number(fields, "inactive_msec"),
        rx_bytes=_number(fields, "rx_bytes"),
        tx_bytes=_number(fields, "tx_bytes"),
    )


class HostapdControl:
    """One connection to the control socket of an interface; close it when done."""

    def __init__(self, interface: str, directory: Path | None = None) -> None:
        base = directory or ctrl_dir()
        self.server = base / interface
        self.local = base / f"{CLIENT_PREFIX}{os.getpid()}-{next(_counter)}"
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            self.local.unlink(missing_ok=True)
            self.sock.bind(str(self.local))
            self.sock.connect(str(self.server))
        except OSError as exc:
            self.close()
            raise WifiError(
                f"cannot reach the access point at {self.server}: {exc.strerror or exc}"
            ) from exc
        self.sock.settimeout(COMMAND_TIMEOUT_SECONDS)

    def close(self) -> None:
        self.sock.close()
        self.local.unlink(missing_ok=True)

    def __enter__(self) -> HostapdControl:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def request(self, command: str) -> str:
        """Send a command and return its reply; events that arrive meanwhile are skipped."""
        try:
            self.sock.send(command.encode())
            while True:
                reply = self.sock.recv(REPLY_BYTES).decode(errors="replace")
                if not reply.startswith("<"):
                    return reply
        except OSError as exc:
            raise WifiError(f"the access point did not answer {command}: {exc}") from exc

    def attach(self) -> None:
        if self.request("ATTACH").strip() != ATTACHED:
            raise WifiError("the access point refused to send its events (ATTACH)")

    def receive(self, timeout: float) -> str | None:
        """The next message within ``timeout`` seconds, or ``None`` when nothing came."""
        self.sock.settimeout(timeout)
        try:
            return self.sock.recv(REPLY_BYTES).decode(errors="replace")
        except TimeoutError:
            return None
        except OSError as exc:
            raise WifiError(f"lost the access point: {exc}") from exc
        finally:
            self.sock.settimeout(COMMAND_TIMEOUT_SECONDS)

    def stations(self) -> list[Station]:
        found: list[Station] = []
        station = parse_station(self.request("STA-FIRST"))
        while station is not None:
            found.append(station)
            station = parse_station(self.request(f"STA-NEXT {station.mac}"))
        return found
