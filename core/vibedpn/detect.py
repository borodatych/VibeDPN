"""Host facts for ``vibedpn init``: the default-route interface with its IPv4 address and the
presence of the WireGuard kernel module.

``HostProbe`` does the I/O (``ip -j`` and ``/sys``); the parsers are pure and unit-tested on real
iproute2 output kept in ``tests/fixtures``.
"""

from __future__ import annotations

import json
import os
import re
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
SSHD = "sshd"
# sshd tokenizes a config line at whitespace or at a single "=" (OpenSSH misc.c, strdelim);
# values may be double-quoted.
SSHD_DELIMITER = re.compile(r"[ \t]*=[ \t]*|[ \t]+")
SSHD_INCLUDE_DEPTH = 16  # sshd refuses deeper nesting (servconf.c, "Include nested too deep")


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


def find_tool(name: str) -> str | None:
    """Locate an admin binary: sbin is off a non-root Debian PATH, so it is searched too."""
    search = os.pathsep.join([*os.get_exec_path(), *SBIN_DIRS])
    return shutil.which(name, path=search)


def find_modprobe() -> str | None:
    return find_tool("modprobe")


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


def sshd_directives(text: str) -> list[tuple[str, str]]:
    """``(keyword, value)`` pairs of one sshd_config text as sshd reads them, outside ``Match``.

    Keywords are lowercased; the value keeps its own tokens but loses surrounding quotes.
    Comments and blank lines are skipped; the same parser reads ``sshd -T`` output.
    """
    directives: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        keyword, *rest = SSHD_DELIMITER.split(line, maxsplit=1)
        keyword = keyword.lower()
        if keyword == "match":
            break
        value = rest[0].strip() if rest else ""
        directives.append((keyword, value.strip('"')))
    return directives


def listen_address_port(value: str) -> int | None:
    """Port of a ``ListenAddress`` value (``host:port``, ``[v6]:port``), ``None`` without one.

    The optional ``rdomain`` tail is dropped; a bare IPv4, hostname or unbracketed IPv6 has no
    port and means "all Port values" (sshd_config(5)).
    """
    tokens = value.split(maxsplit=1)
    address = tokens[0] if tokens else ""
    if address.startswith("["):
        _, bracket, port = address.partition("]:")
        return int(port) if bracket and port.isdigit() else None
    if address.count(":") == 1:
        _, _, port = address.partition(":")
        return int(port) if port.isdigit() else None
    return None


def ports_from_directives(directives: list[tuple[str, str]]) -> list[int]:
    """Ports sshd listens on given its directives, in order.

    ``ListenAddress`` with a port pins that port; a ``ListenAddress`` without one, or none at
    all, listens on every ``Port`` (22 when there is no ``Port`` either).
    """
    port_values: list[int] = []
    pinned: list[int] = []
    listen_without_port = False
    listen_seen = False
    for keyword, value in directives:
        if keyword == "port" and value.isdigit():
            port_values.append(int(value))
        elif keyword == "listenaddress":
            listen_seen = True
            port = listen_address_port(value)
            if port is None:
                listen_without_port = True
            else:
                pinned.append(port)
    ports = list(pinned)
    if not listen_seen or listen_without_port:
        ports.extend(port_values or [DEFAULT_SSH_PORT])
    return list(dict.fromkeys(ports))


def parse_sshd_ports(text: str) -> list[int]:
    """Ports sshd listens on per one config text (or ``sshd -T`` output)."""
    return ports_from_directives(sshd_directives(text))


def parse_sshd_includes(text: str) -> list[str]:
    """``Include`` patterns of one sshd_config text, in order."""
    return [
        pattern
        for keyword, value in sshd_directives(text)
        if keyword == "include"
        for pattern in value.split()
    ]


def expand_includes(text: str, root: Path, depth: int = 0) -> list[tuple[str, str]]:
    """Directives of one file with every ``Include`` replaced, in place, by the directives of
    the files it names (lexical order, relative to ``root``) — the way sshd reads them, so a
    ``Match`` block at the end of the main file hides nothing from ``sshd_config.d/``."""
    directives: list[tuple[str, str]] = []
    for keyword, value in sshd_directives(text):
        if keyword != "include" or depth >= SSHD_INCLUDE_DEPTH:
            directives.append((keyword, value))
            continue
        for pattern in value.split():
            base = Path(pattern) if pattern.startswith("/") else root / pattern
            for path in sorted(base.parent.glob(base.name)):
                try:
                    included = path.read_text(encoding="utf-8")
                except OSError:
                    continue
                directives.extend(expand_includes(included, root, depth + 1))
    return directives


def sshd_ports(main: Path = SSHD_CONFIG, root: Path = SSHD_CONFIG_ROOT) -> list[int]:
    """Ports sshd listens on per its config files; a missing config means a stock sshd on 22."""
    try:
        text = main.read_text(encoding="utf-8")
    except OSError:
        return [DEFAULT_SSH_PORT]
    return ports_from_directives(expand_includes(text, root))


def sshd_effective_ports() -> list[int] | None:
    """Ports from ``sshd -T`` — the daemon's own view (Include, ``=``, quotes, defaults all
    resolved); ``None`` when sshd is absent or refuses (needs root: it loads the host keys)."""
    sshd = find_tool(SSHD)
    if sshd is None:
        return None
    try:
        probe = subprocess.run([sshd, "-T"], check=False, capture_output=True, text=True)
    except OSError:
        return None
    if probe.returncode != 0:
        return None
    return parse_sshd_ports(probe.stdout)


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
        """The daemon's own answer when it gives one, else its config files."""
        return sshd_effective_ports() or sshd_ports()

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
