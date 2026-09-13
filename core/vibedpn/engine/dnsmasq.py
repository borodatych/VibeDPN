"""dnsmasq of gateway mode: DHCP on the LAN side, rendered by core like AdGuardHome.yaml.

Only DHCP (``port=0``): names are answered by AdGuard, and in sidecar mode no dnsmasq runs at all —
the Compose profile ``dhcp`` exists only in gateway mode, so the box never hands out addresses next
to the DHCP server of an ISP router. Lease file format: docs/knowledge/linux/dnsmasqLeases.md.
"""

from __future__ import annotations

import os
from pathlib import Path

from vibedpn.atomic import write_private
from vibedpn.config import Config, NetworkMode

CONF_FILE = "dnsmasq.conf"
LEASE_FILE = "leases"
# The directory compose.yaml mounts into the dnsmasq container (./data/dnsmasq).
CONTAINER_DIR = "/var/lib/vibedpn-dnsmasq"
# The same directory as core sees it (compose.yaml mounts ./data/dnsmasq there).
DIR_ENV = "VIBEDPN_DNSMASQ_CONF"
DEFAULT_DIR = Path("/etc/vibedpn/dnsmasq")


def core_dir() -> Path:
    return Path(os.environ.get(DIR_ENV, DEFAULT_DIR))


class DnsmasqError(RuntimeError):
    """A user-facing reason why the dnsmasq configuration could not be written."""


def dnsmasq_conf(config: Config) -> str | None:
    """The configuration of a gateway box, ``None`` for any other."""
    network = config.network
    if network is None or network.mode is not NetworkMode.GATEWAY:
        return None
    start, end = network.dhcp_pool()
    lease = network.dhcp.lease if network.dhcp is not None else "12h"
    lines = [
        "# Rendered by vibedpn core from config.yaml at every start; edit config.yaml instead.",
        "port=0",
        f"interface={network.lan_interface}",
        "bind-interfaces",
        "dhcp-authoritative",
        f"dhcp-range={start},{end},{lease}",
        f"dhcp-option=option:router,{network.lan_address}",
        f"dhcp-leasefile={CONTAINER_DIR}/{LEASE_FILE}",
    ]
    if config.dns.enabled:
        lines.append(f"dhcp-option=option:dns-server,{network.lan_address}")
    return "\n".join(lines) + "\n"


def ensure_dnsmasq(config: Config, conf_dir: Path) -> bool | None:
    """Write ``dnsmasq.conf``; ``None`` on a box without gateway mode, else whether it changed."""
    text = dnsmasq_conf(config)
    if text is None:
        return None
    try:
        conf_dir.mkdir(parents=True, exist_ok=True)
        return write_private(conf_dir / CONF_FILE, text)
    except OSError as exc:
        raise DnsmasqError(f"cannot write {conf_dir / CONF_FILE}: {exc.strerror or exc}") from exc
