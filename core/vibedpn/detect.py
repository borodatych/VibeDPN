"""Host facts for ``vibedpn init``: the default-route interface with its IPv4 address and the
presence of the WireGuard kernel module.

``HostProbe`` does the I/O (``ip -j`` and ``/sys``); the parsers are pure and unit-tested on real
iproute2 output kept in ``tests/fixtures``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Interface, IPv4Network
from pathlib import Path

SYSFS_MODULES = Path("/sys/module")
WIREGUARD_MODULE = "wireguard"
SBIN_DIRS = ("/usr/local/sbin", "/usr/sbin", "/sbin")  # Debian keeps sbin off a user's PATH


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


def find_modprobe() -> str | None:
    """``modprobe`` lives in sbin, which a non-root Debian PATH does not include."""
    search = os.pathsep.join([*os.get_exec_path(), *SBIN_DIRS])
    return shutil.which("modprobe", path=search)


def module_present(name: str) -> bool | None:
    """``True``: loaded (sysfs) or loadable (``modprobe -n``); ``False``: modprobe says no;
    ``None``: no modprobe at hand, cannot tell.

    A built-in or not-yet-loaded module has no sysfs entry, so sysfs alone would say "no" on a
    host that is perfectly fine; ``modprobe -n`` answers for both cases.
    """
    if (SYSFS_MODULES / name).exists():
        return True
    modprobe = find_modprobe()
    if modprobe is None:
        return None
    probe = subprocess.run([modprobe, "-n", "-q", name], check=False, capture_output=True)
    return probe.returncode == 0


class HostProbe:
    """Reads host facts through ``ip`` and ``/sys``; replaced by a fake in tests."""

    def default_interface(self) -> Interface | None:
        name = parse_default_route(self._ip("route", "show", "default"))
        if name is None:
            return None
        return parse_interface(self._ip("addr", "show", "dev", name), name)

    def wireguard_module_present(self) -> bool | None:
        return module_present(WIREGUARD_MODULE)

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
