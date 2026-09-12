"""Host facts for ``vibedpn init``: the default-route interface with its IPv4 address and the
presence of the WireGuard kernel module.

``HostProbe`` does the I/O (``ip -j`` and ``/sys``); the parsers are pure and unit-tested on real
iproute2 output kept in ``tests/fixtures``.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Interface, IPv4Network
from pathlib import Path

WIREGUARD_MODULE_SYSFS = Path("/sys/module/wireguard")


class DetectError(RuntimeError):
    """The host could not be probed (missing tool, failing command)."""


@dataclass(frozen=True)
class Interface:
    """An interface with its primary global IPv4 address."""

    name: str
    address: IPv4Address
    prefixlen: int

    @property
    def subnet(self) -> IPv4Network:
        return IPv4Interface(f"{self.address}/{self.prefixlen}").network


def parse_default_route(text: str) -> str | None:
    """Interface name of the first default route in ``ip -j -4 route show default`` output."""
    for route in json.loads(text):
        if route.get("dst") == "default" and route.get("dev"):
            return str(route["dev"])
    return None


def parse_interface(text: str, name: str) -> Interface | None:
    """First global IPv4 address of interface ``name`` in ``ip -j -4 addr show`` output."""
    for link in json.loads(text):
        if link.get("ifname") != name:
            continue
        for info in link.get("addr_info", []):
            if info.get("family") == "inet" and info.get("scope") == "global":
                return Interface(name, IPv4Address(info["local"]), int(info["prefixlen"]))
    return None


class HostProbe:
    """Reads host facts through ``ip`` and ``/sys``; replaced by a fake in tests."""

    def default_interface(self) -> Interface | None:
        name = parse_default_route(self._ip("route", "show", "default"))
        if name is None:
            return None
        return parse_interface(self._ip("addr", "show", "dev", name), name)

    def wireguard_module_present(self) -> bool:
        if WIREGUARD_MODULE_SYSFS.exists():
            return True
        try:
            probe = subprocess.run(
                ["modprobe", "-n", "-q", "wireguard"], check=False, capture_output=True
            )
        except FileNotFoundError:
            return False
        return probe.returncode == 0

    @staticmethod
    def _ip(*args: str) -> str:
        try:
            result = subprocess.run(
                ["ip", "-j", "-4", *args], check=True, capture_output=True, text=True
            )
        except FileNotFoundError as exc:
            raise DetectError("`ip` not found: install iproute2") from exc
        except subprocess.CalledProcessError as exc:
            raise DetectError(f"`ip {' '.join(args)}` failed: {exc.stderr.strip()}") from exc
        return result.stdout
