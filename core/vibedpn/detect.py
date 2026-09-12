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
SSHD_CONFIG = Path("/etc/ssh/sshd_config")
SSHD_CONFIG_ROOT = Path("/etc/ssh")  # relative Include paths resolve here (sshd_config(5))
DEFAULT_SSH_PORT = 22


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


def parse_sshd_ports(text: str) -> list[int]:
    """``Port`` values of one sshd_config text, outside ``Match`` blocks, in order."""
    ports: list[int] = []
    in_match = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        keyword, _, value = line.partition(" ")
        keyword = keyword.lower()
        if keyword == "match":
            in_match = True
            continue
        if in_match:
            continue
        if keyword == "port" and value.strip().isdigit():
            port = int(value.strip())
            if port not in ports:
                ports.append(port)
    return ports


def parse_sshd_includes(text: str) -> list[str]:
    """``Include`` patterns of one sshd_config text, in order."""
    patterns: list[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        keyword, _, value = line.partition(" ")
        if keyword.lower() == "include":
            patterns.extend(value.split())
    return patterns


def sshd_ports(main: Path = SSHD_CONFIG, root: Path = SSHD_CONFIG_ROOT) -> list[int]:
    """Every port sshd listens on per its config (all ``Port`` lines count), default 22.

    Included files are read in lexical order; a missing config means a stock sshd on 22.
    """
    texts: list[str] = []
    try:
        texts.append(main.read_text(encoding="utf-8"))
    except OSError:
        return [DEFAULT_SSH_PORT]
    for pattern in parse_sshd_includes(texts[0]):
        base = Path(pattern) if pattern.startswith("/") else root / pattern
        for path in sorted(base.parent.glob(base.name)):
            try:
                texts.append(path.read_text(encoding="utf-8"))
            except OSError:
                continue
    ports: list[int] = []
    for text in texts:
        for port in parse_sshd_ports(text):
            if port not in ports:
                ports.append(port)
    return ports or [DEFAULT_SSH_PORT]


class HostProbe:
    """Reads host facts through ``ip`` and ``/sys``; replaced by a fake in tests."""

    def default_interface(self) -> Interface | None:
        name = parse_default_route(self._ip("route", "show", "default"))
        if name is None:
            return None
        return parse_interface(self._ip("addr", "show", "dev", name), name)

    def wireguard_module_present(self) -> bool | None:
        return module_present(WIREGUARD_MODULE)

    def ssh_ports(self) -> list[int]:
        return sshd_ports()

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
