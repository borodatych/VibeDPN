"""Host networking of the box, rendered from templates and applied through ``nft``.

The only module allowed to change host networking. It never touches the host default route.
Stage 2 ships the VPS firewall (table ``inet vibedpn``, input policy drop); Stage 3 lets tunnel
peers out through the VPS (table ``inet vibedpn_egress`` plus the ``DOCKER-USER`` rules that open
Docker's forward drop); the LAN router (fwmarks, ``ip rule``, gateway tables) arrives in Stage 4
and extends this module.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum
from itertools import takewhile

from vibedpn.config import (
    WG_KEY_PREFIX,
    Config,
    DevicePolicy,
    DomainChannel,
    DomainVia,
    Role,
    RoutingMode,
    Upstream,
    parse_port_range,
)
from vibedpn.detect import SBIN_DIRS
from vibedpn.engine.myst import NODEUI_PORT
from vibedpn.engine.resolver import channel_set, smart_set_names
from vibedpn.templating import template_environment

NFT = "nft"
NFT_TABLE = "inet vibedpn"
WG_INTERFACE = "wg0"
FIREWALL_TEMPLATE = "firewall.nft.j2"
# One transaction that ends without the table whether or not it was loaded: ``delete`` alone
# fails on a missing table, ``add`` of an existing one is a no-op.
FIREWALL_TEARDOWN = f"add table {NFT_TABLE}\ndelete table {NFT_TABLE}\n"
EGRESS_TABLE = "inet vibedpn_egress"
EGRESS_TEMPLATE = "tunnel-egress.nft.j2"
EGRESS_TEARDOWN = f"add table {EGRESS_TABLE}\ndelete table {EGRESS_TABLE}\n"
# Docker sets the iptables FORWARD policy to drop, and an accept in our own nft table cannot
# override a drop in another one; DOCKER-USER is the chain Docker leaves to the host owner.
DOCKER_USER = "DOCKER-USER"
OUR_COMMENT_PREFIX = "vibedpn-"  # every group of ours in DOCKER-USER is commented with it
EGRESS_COMMENT = "vibedpn-egress"  # marks our rules among the owner's in DOCKER-USER
ROUTER_COMMENT = "vibedpn-router"
ROUTER_TABLE = "inet vibedpn_router"
ROUTER_TEMPLATE = "lan-router.nft.j2"
ROUTER_TEARDOWN = f"add table {ROUTER_TABLE}\ndelete table {ROUTER_TABLE}\n"
# The bridge of the `upstreams` network: com.docker.network.bridge.name in compose.yaml.
UPSTREAMS_BRIDGE = "vibedpn0"
UPSTREAMS_SUBNET = "10.77.0.0/24"
IP = "ip"
# The kill switch of an uplink table: the worst possible metric, so the gateway route always wins
# while it exists, and marked traffic has nowhere else to go once it is gone.
LAST_RESORT_METRIC = 4294967295
# `ip route del` of a route that is not there, and `ip route del|flush` in a table that was
# never created (both texts seen on iproute2 of alpine 3.24, 2026-09-13).
MISSING_ROUTE_ERRORS = ("No such process", "FIB table does not exist")
IPTABLES_BACKENDS = ("iptables-nft", "iptables-legacy")
NO_CHAIN = "No chain/target/match by that name"
# Peers get the internet, not the VPS's neighbourhood: link-local (cloud metadata), RFC 1918
# (VPC, Docker networks) and CGNAT. Traffic to the tunnel itself never matches (oifname wg0).
EGRESS_BLOCKED_RANGES = (
    "169.254.0.0/16",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "100.64.0.0/10",
)


class RouterError(RuntimeError):
    """A user-facing reason why host rules could not be rendered or applied."""


def firewall_ruleset(config: Config) -> str | None:
    """The nftables ruleset of a VPS, or ``None`` when this box has no host firewall."""
    if config.role is not Role.VPS or not config.firewall.enabled:
        return None
    udp_from = udp_to = None
    if config.provider.enabled:
        udp_from, udp_to = parse_port_range(config.provider.udp_ports)
    return (
        template_environment()
        .get_template(FIREWALL_TEMPLATE)
        .render(
            ssh_ports=config.firewall.ssh_ports,
            wg_port=config.wg_server.listen_port if config.wg_server else None,
            provider=config.provider.enabled,
            udp_from=udp_from,
            udp_to=udp_to,
            wg_interface=WG_INTERFACE,
            tunnel_subnet=str(config.wg_server.subnet) if config.wg_server else None,
            tunnel_tcp_ports=[NODEUI_PORT, config.api.port],
            allow_tcp=config.firewall.allow_tcp,
            allow_udp=config.firewall.allow_udp,
        )
    )


def ssh_rule_present(ruleset: str, ssh_ports: list[int]) -> bool:
    """A guard against a template regression: the rendered text must accept every configured
    ssh port. Whether sshd really listens there is ``doctor``'s check, not this one's."""
    return f"tcp dport {{ {', '.join(str(p) for p in ssh_ports)} }} accept" in ruleset


def find_nft() -> str | None:
    """``nft`` lives in sbin, which a non-root PATH does not include."""
    search = os.pathsep.join([*os.get_exec_path(), *SBIN_DIRS])
    return shutil.which(NFT, path=search)


def _nft(args: list[str], ruleset: str) -> None:
    nft = find_nft()
    if nft is None:
        raise RouterError(
            "nft not found (the core image installs nftables; on a host: apt install nftables)"
        )
    try:
        completed = subprocess.run(
            [nft, *args], input=ruleset, check=False, capture_output=True, text=True
        )
    except OSError as exc:
        raise RouterError(f"cannot run nft: {exc.strerror}") from exc
    if completed.returncode != 0:
        raise RouterError(f"nft {' '.join(args)} failed: {completed.stderr.strip()}")


def check_ruleset(ruleset: str) -> None:
    """Parse-only pass (``nft -c``) so a rendering mistake never reaches the kernel."""
    _nft(["-c", "-f", "-"], ruleset)


def apply_ruleset(ruleset: str) -> None:
    """Load the ruleset atomically; the file replaces the whole table, so it is idempotent."""
    _nft(["-f", "-"], ruleset)


def remove_firewall() -> None:
    """Drop the table if it is loaded, so a disabled or changed configuration is the truth."""
    _nft(["-f", "-"], FIREWALL_TEARDOWN)


class Egress(StrEnum):
    """What ``apply_tunnel_egress`` left on the host."""

    NONE = "none"  # no tunnel in this configuration; leftovers removed
    DOCKER_USER = "docker-user"  # table loaded, Docker's forward drop opened in DOCKER-USER
    NO_DOCKER_DROP = "no-docker-drop"  # table loaded, no DOCKER-USER chain to open


def egress_ruleset(config: Config) -> str | None:
    """Forward and NAT of the tunnel subnet on a VPS, or ``None`` when there is no tunnel."""
    if config.role is not Role.VPS or config.wg_server is None:
        return None
    return (
        template_environment()
        .get_template(EGRESS_TEMPLATE)
        .render(
            wg_interface=WG_INTERFACE,
            tunnel_subnet=str(config.wg_server.subnet),
            private_ranges=EGRESS_BLOCKED_RANGES,
        )
    )


def docker_user_rules(config: Config) -> list[list[str]]:
    """``DOCKER-USER`` rules in the exact form ``iptables -S`` prints them back, so a listing
    compares equal to what is wanted. Empty when this configuration has no tunnel."""
    if config.role is not Role.VPS or config.wg_server is None:
        return []
    subnet = str(config.wg_server.subnet)
    comment = ["-m", "comment", "--comment", EGRESS_COMMENT]
    return [
        ["-s", subnet, "-i", WG_INTERFACE, "!", "-o", WG_INTERFACE, *comment, "-j", "ACCEPT"],
        [
            "-d", subnet, "!", "-i", WG_INTERFACE, "-o", WG_INTERFACE,
            "-m", "conntrack", "--ctstate", "RELATED,ESTABLISHED", *comment, "-j", "ACCEPT",
        ],
    ]  # fmt: skip


def _commented_by_us(rule: list[str]) -> bool:
    if "--comment" not in rule:
        return False
    position = rule.index("--comment") + 1
    return position < len(rule) and rule[position].startswith(OUR_COMMENT_PREFIX)


def plan_docker_user(
    listing: str, wanted: list[list[str]], comment: str
) -> tuple[list[list[str]], list[list[str]]]:
    """``(delete, insert)`` that turns our ``comment`` group in ``iptables -S DOCKER-USER`` into
    ``wanted``: rules of an old subnet and duplicates go, missing ones come; foreign rules are
    untouched. A group counts as in place only above every foreign rule — an owner's DROP or
    Docker's RETURN above it would make it dead — so then the whole group is reinserted at the
    top. Other VibeDPN groups may sit among ours: two groups must not push each other down."""
    rules = [
        args[2:]
        for line in listing.splitlines()
        if (args := shlex.split(line))[:2] == ["-A", DOCKER_USER]
    ]
    head = list(takewhile(_commented_by_us, rules))
    ours = [rule for rule in rules if comment in rule]
    in_head = [rule for rule in head if comment in rule]
    if len(ours) == len(wanted) and sorted(in_head) == sorted(wanted):
        return [], []
    return ours, list(wanted)


def find_iptables() -> list[str]:
    """Installed iptables backends, nft first; they live in sbin like ``nft``."""
    search = os.pathsep.join([*os.get_exec_path(), *SBIN_DIRS])
    return [path for name in IPTABLES_BACKENDS if (path := shutil.which(name, path=search))]


def docker_user_chain() -> tuple[str, str] | None:
    """``(iptables binary, listing)`` of the backend whose filter table has ``DOCKER-USER``, or
    ``None`` when neither backend has the chain (Docker with its nftables backend, or no Docker).
    Raises when no iptables is installed or the listing fails for another reason."""
    binaries = find_iptables()
    if not binaries:
        raise RouterError(
            "iptables not found (the core image installs it; on a host: apt install iptables)"
        )
    for binary in binaries:
        try:
            listing = subprocess.run(
                [binary, "-w", "-S", DOCKER_USER], check=False, capture_output=True, text=True
            )
        except OSError as exc:
            raise RouterError(f"cannot run {binary}: {exc.strerror}") from exc
        if listing.returncode == 0:
            return binary, listing.stdout
        # The legacy backend fails in its own ways on an nft host (no ip_tables module): only the
        # backend Docker actually uses can have the chain, so any legacy failure means "not here".
        if NO_CHAIN not in listing.stderr and not binary.endswith("legacy"):
            raise RouterError(f"{binary} -S {DOCKER_USER} failed: {listing.stderr.strip()}")
    return None


def sync_docker_user(wanted: list[list[str]], comment: str) -> bool:
    """Make our ``comment`` group in ``DOCKER-USER`` exactly ``wanted``; ``False`` when there
    is no such chain."""
    found = docker_user_chain()
    if found is None:
        return False
    binary, listing = found
    delete, insert = plan_docker_user(listing, wanted, comment)
    commands = [["-D", DOCKER_USER, *rule] for rule in delete]
    # Inserted at the top: Docker may end the chain with RETURN on older versions.
    commands += [["-I", DOCKER_USER, "1", *rule] for rule in reversed(insert)]
    for command in commands:
        completed = subprocess.run(
            [binary, "-w", *command], check=False, capture_output=True, text=True
        )
        if completed.returncode != 0:
            raise RouterError(
                f"{binary} {' '.join(command[:2])} failed: {completed.stderr.strip()}"
            )
    return True


def apply_tunnel_egress(config: Config) -> Egress:
    """Let tunnel peers out to the internet: NAT and forward table, then ``DOCKER-USER``.
    Without a tunnel both are removed, so a VPS that stopped serving peers forwards nothing."""
    ruleset = egress_ruleset(config)
    if ruleset is None:
        # DOCKER-USER first: a failing nft must not leave the forward drop opened.
        if find_iptables():  # without iptables nothing of ours can be in DOCKER-USER either
            sync_docker_user([], EGRESS_COMMENT)
        _nft(["-f", "-"], EGRESS_TEARDOWN)
        return Egress.NONE
    check_ruleset(ruleset)
    apply_ruleset(ruleset)
    if sync_docker_user(docker_user_rules(config), EGRESS_COMMENT):
        return Egress.DOCKER_USER
    return Egress.NO_DOCKER_DROP


@dataclass(frozen=True)
class Uplink:
    mark: int  # fwmark the LAN router sets on traffic of this uplink
    table: int  # routing table id, also the priority of its ip rule
    gateway: str  # static address of the gateway container in compose.yaml


UPLINKS: dict[Upstream, Uplink] = {
    Upstream.VPS: Uplink(mark=0x10, table=7710, gateway="10.77.0.10"),
    Upstream.DPN: Uplink(mark=0x20, table=7720, gateway="10.77.0.20"),
    # 0x30 is BLOCK_MARK; countries take 0x40+i, named WireGuard exits 0x50+i.
    Upstream.TOR: Uplink(mark=0x60, table=7760, gateway="10.77.0.60"),
}
# Countries of routing.domains and routing.lists get their own consumer (docs/decisions.md, 20):
# the i-th country in sorted order has mark 0x40+i, table 7740+i and gateway 10.77.0.40+i.
MAX_COUNTRIES = 8
COUNTRY_MARK_BASE = 0x40
COUNTRY_TABLE_BASE = 7740
COUNTRY_GATEWAY_BASE = 40  # last octet in UPSTREAMS_SUBNET


def rule_countries(config: Config) -> list[str]:
    """The exit countries domain rules ask for, sorted: each one is a consumer of its own."""
    channels = config.routing.channels() if config.routing is not None else []
    return sorted({item.country for item in channels if item.via is DomainVia.DPN and item.country})


def country_uplinks(config: Config) -> dict[str, Uplink]:
    """Country → its uplink; the numbering follows the sorted set, which changes only on restart."""
    return {
        country: Uplink(
            mark=COUNTRY_MARK_BASE + index,
            table=COUNTRY_TABLE_BASE + index,
            gateway=f"10.77.0.{COUNTRY_GATEWAY_BASE + index}",
        )
        for index, country in enumerate(rule_countries(config))
    }


COUNTRY_KEY_PREFIX = "dpn-"
COUNTRY_SLOTS = [
    Uplink(
        mark=COUNTRY_MARK_BASE + index,
        table=COUNTRY_TABLE_BASE + index,
        gateway=f"10.77.0.{COUNTRY_GATEWAY_BASE + index}",
    )
    for index in range(MAX_COUNTRIES)
]


def country_key(country: str) -> str:
    return f"{COUNTRY_KEY_PREFIX}{country.lower()}"


MAX_WG_UPLINKS = 8
WG_MARK_BASE = 0x50
WG_TABLE_BASE = 7750
WG_GATEWAY_BASE = 50  # last octet in UPSTREAMS_SUBNET


def wg_key(name: str) -> str:
    return f"{WG_KEY_PREFIX}{name}"


def wg_uplinks(config: Config) -> dict[str, Uplink]:
    """Name → its uplink for every named WireGuard exit, in the sorted order of the names.

    The numbering follows that order, exactly as the country consumers do: it changes only when
    the owner adds or removes a name, which needs a restart anyway.
    """
    return {
        name: Uplink(
            mark=WG_MARK_BASE + index,
            table=WG_TABLE_BASE + index,
            gateway=f"10.77.0.{WG_GATEWAY_BASE + index}",
        )
        for index, name in enumerate(sorted(config.upstreams.wg))
    }


def uplink_table(config: Config) -> dict[str, Uplink]:
    """Every uplink this configuration may use, by key: vps, dpn, dpn-<cc> per rule country, and
    wg-<name> per named WireGuard exit."""
    table: dict[str, Uplink] = {upstream.value: uplink for upstream, uplink in UPLINKS.items()}
    table.update({country_key(cc): uplink for cc, uplink in country_uplinks(config).items()})
    table.update({wg_key(name): uplink for name, uplink in wg_uplinks(config).items()})
    return table


def uplink_service(key: str) -> str:
    """The Compose service of an uplink key."""
    if key.startswith(COUNTRY_KEY_PREFIX):
        return f"myst-consumer-{key.removeprefix(COUNTRY_KEY_PREFIX)}"
    if key.startswith(WG_KEY_PREFIX):
        return key  # the generated service is named after the key: wg-<name>
    return {
        Upstream.VPS.value: "wg-client",
        Upstream.DPN.value: "myst-consumer",
        Upstream.TOR.value: "tor",
    }[key]


# Device policies that send a device through an uplink.
POLICY_UPLINKS: dict[DevicePolicy, Upstream] = {
    DevicePolicy.VPS: Upstream.VPS,
    DevicePolicy.DPN: Upstream.DPN,
    DevicePolicy.TOR: Upstream.TOR,
}
# policy block: no ip rule knows this mark, and the forward chain drops it.
BLOCK_MARK = 0x30
# Domain rules of routing.mode smart that leave through an uplink; `direct` needs no mark.
RULE_UPLINKS: dict[DomainVia, Upstream] = {
    DomainVia.VPS: Upstream.VPS,
    DomainVia.DPN: Upstream.DPN,
    DomainVia.TOR: Upstream.TOR,
}
# AdGuard Home runs as this user (compose.yaml `user:`), so its own DoH traffic can be told from
# the host's and steered into the uplink of routing.mode full (docs/decisions.md, decision 14).
ADGUARD_UID = 7753


def active_uplink(config: Config) -> str | None:
    """The uplink key LAN traffic leaves through, or ``None`` when everything goes direct."""
    if config.network is None or config.routing is None:
        return None
    if config.routing.mode is not RoutingMode.FULL:
        return None  # off: everything direct; smart: each rule names its own channel
    return config.routing.default_upstream


def used_uplinks(config: Config) -> list[str]:
    """Every uplink some LAN traffic may take, by key: the one of routing.mode full, the ones device
    policies name, and in smart the ones domain rules name (a rule country has its own). Each needs
    its ip rule, its table with the kill switch and a watcher."""
    wanted: set[str] = set()
    active = active_uplink(config)
    if active is not None:
        wanted.add(active)
    if config.routing is not None and config.routing.mode is RoutingMode.SMART:
        for item in config.routing.channels():
            if item.via is DomainVia.DPN and item.country:
                wanted.add(country_key(item.country))
            elif item.via is DomainVia.WG and item.uplink:
                wanted.add(wg_key(item.uplink))
            elif item.via in RULE_UPLINKS:
                wanted.add(RULE_UPLINKS[item.via].value)
    if config.network is not None:
        wanted.update(
            POLICY_UPLINKS[device.policy].value
            for device in config.devices
            if device.policy in POLICY_UPLINKS
        )
    return [key for key in uplink_table(config) if key in wanted]


@dataclass(frozen=True)
class DeviceSet:
    name: str
    type: str
    elements: list[str]


def device_sets(config: Config) -> list[DeviceSet]:
    """Two nft sets per policy: MACs, and the addresses of devices that have no MAC in config."""
    sets = []
    for policy in DevicePolicy:
        devices = [device for device in config.devices if device.policy is policy]
        sets.append(
            DeviceSet(
                f"devices_{policy.value}_mac",
                "ether_addr",
                [device.mac for device in devices if device.mac is not None],
            )
        )
        sets.append(
            DeviceSet(
                f"devices_{policy.value}_ip",
                "ipv4_addr",
                [str(device.ip) for device in devices if device.mac is None and device.ip],
            )
        )
    return sets


@dataclass(frozen=True)
class UplinkPolicy:
    name: str
    mark: str


def _channel_mark(item: DomainChannel, table: dict[str, Uplink]) -> str | None:
    """The mark of a channel's uplink; ``None`` for direct. A country takes its own consumer's."""
    if item.via is DomainVia.DPN and item.country:
        return hex(table[country_key(item.country)].mark)
    if item.via is DomainVia.WG and item.uplink:
        return hex(table[wg_key(item.uplink)].mark)
    if item.via in RULE_UPLINKS:
        return hex(UPLINKS[RULE_UPLINKS[item.via]].mark)
    return None


def smart_marks(config: Config) -> list[UplinkPolicy]:
    """routing.mode smart: the channel sets that carry an uplink mark; a set of a country takes the
    mark of that country's own consumer."""
    if config.routing is None or config.routing.mode is not RoutingMode.SMART:
        return []
    table = uplink_table(config)
    marks = {}
    for item in config.routing.channels():
        mark = _channel_mark(item, table)
        if mark is not None:
            marks[channel_set(item)] = mark
    return [UplinkPolicy(name, mark) for name, mark in sorted(marks.items())]


NETWORK_SET_SUFFIX = "_net"


@dataclass(frozen=True)
class NetworkSet:
    name: str
    mark: str  # "" for direct: the addresses return before any other smart mark
    elements: list[str]


def smart_networks(config: Config) -> list[NetworkSet]:
    """routing.mode smart: one interval set per channel of routing.networks, direct ones first, so a
    network the owner keeps direct is never caught by a wider one sent through an uplink."""
    if config.routing is None or config.routing.mode is not RoutingMode.SMART:
        return []
    table = uplink_table(config)
    elements: dict[str, list[str]] = {}
    marks: dict[str, str] = {}
    for item in config.routing.networks:
        name = f"{channel_set(item)}{NETWORK_SET_SUFFIX}"
        elements.setdefault(name, []).append(str(item.network))
        marks[name] = _channel_mark(item, table) or ""
    return sorted(
        (NetworkSet(name, marks[name], sorted(values)) for name, values in elements.items()),
        key=lambda item: (item.mark != "", item.name),
    )


def router_ruleset(config: Config) -> str | None:
    """The nftables ruleset of a LAN box, or ``None`` when this box routes no LAN."""
    if config.network is None:
        return None
    active = active_uplink(config)
    return (
        template_environment()
        .get_template(ROUTER_TEMPLATE)
        .render(
            lan_interface=config.network.lan_interface,
            lan_subnet=str(config.network.lan_subnet),
            upstreams_subnet=UPSTREAMS_SUBNET,
            bridge=UPSTREAMS_BRIDGE,
            sets=device_sets(config),
            # channel sets of routing.domains, filled by the resolver of core (engine/resolver.py)
            smart_sets=smart_set_names(config),
            # tunnel channels first: an address two rules share (one CDN) leaves through the tunnel
            smart_marks=smart_marks(config),
            # networks of routing.networks: static interval sets, matched before the domain sets
            smart_networks=smart_networks(config),
            block_mark=hex(BLOCK_MARK),
            uplink_policies=[
                UplinkPolicy(policy.value, hex(UPLINKS[upstream].mark))
                for policy, upstream in POLICY_UPLINKS.items()
            ],
            mode_upstream=active or "",
            mode_mark=hex(uplink_table(config)[active].mark) if active else "",
            # The VPS forwards no peer to private ranges (tunnel egress), so the only private
            # target behind the tunnel is the VPS itself: its node panel and core API. Closing
            # the ranges needs no knowledge of the tunnel subnet, which the peer file lacks.
            vps_lan_closed=config.upstreams.vps.enabled and not config.upstreams.vps.lan_access,
            vps_mark=hex(UPLINKS[Upstream.VPS].mark),
            private_ranges=EGRESS_BLOCKED_RANGES,
            # routing.mode full with AdGuard: its upstream queries leave through the same uplink
            dns_mark=hex(uplink_table(config)[active].mark)
            if active and config.dns.enabled
            else "",
            adguard_uid=ADGUARD_UID,
            # gateway mode: the box is the router of its LAN, so the direct path is NATed here
            wan_interface=config.network.wan_interface or "",
        )
    )


def router_docker_user_rules(config: Config) -> list[list[str]]:
    """Transit Docker's forward drop would kill: LAN ↔ gateway bridge, and LAN ↔ LAN for the
    direct path of a one-port box. In ``iptables -S`` form, like ``docker_user_rules``, and in
    this order: ``sync_docker_user`` inserts a group keeping it."""
    if config.network is None:
        return []
    lan = config.network.lan_interface
    subnet = str(config.network.lan_subnet)
    comment = ["-m", "comment", "--comment", ROUTER_COMMENT]
    replies = ["-m", "conntrack", "--ctstate", "RELATED,ESTABLISHED"]
    return [
        ["-s", subnet, "-i", lan, "-o", UPSTREAMS_BRIDGE, *comment, "-j", "ACCEPT"],
        ["-d", subnet, "-i", UPSTREAMS_BRIDGE, "-o", lan, *replies, *comment, "-j", "ACCEPT"],
        # A gateway container is a third-party image: it answers the LAN, it never calls into it.
        ["-i", UPSTREAMS_BRIDGE, "-o", lan, *comment, "-j", "DROP"],
        ["-s", subnet, "-i", lan, "-o", lan, *comment, "-j", "ACCEPT"],
        ["-d", subnet, "-i", lan, "-o", lan, *replies, *comment, "-j", "ACCEPT"],
        *_gateway_transit(config, comment, replies),
    ]


def _gateway_transit(config: Config, comment: list[str], replies: list[str]) -> list[list[str]]:
    """gateway mode: the direct path of the LAN leaves through the WAN interface of the box."""
    network = config.network
    if network is None or network.wan_interface is None:
        return []
    lan, wan, subnet = network.lan_interface, network.wan_interface, str(network.lan_subnet)
    return [
        ["-s", subnet, "-i", lan, "-o", wan, *comment, "-j", "ACCEPT"],
        ["-d", subnet, "-i", wan, "-o", lan, *replies, *comment, "-j", "ACCEPT"],
    ]


def find_ip() -> str | None:
    search = os.pathsep.join([*os.get_exec_path(), *SBIN_DIRS])
    return shutil.which(IP, path=search)


def _ip(args: list[str], *, missing_ok: bool = False) -> str:
    ip = find_ip()
    if ip is None:
        raise RouterError(
            "ip not found (the core image installs iproute2; on a host: apt install iproute2)"
        )
    try:
        completed = subprocess.run([ip, *args], check=False, capture_output=True, text=True)
    except OSError as exc:
        raise RouterError(f"cannot run ip: {exc.strerror}") from exc
    if completed.returncode != 0:
        if missing_ok and any(text in completed.stderr for text in MISSING_ROUTE_ERRORS):
            return ""
        raise RouterError(f"ip {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout


def _rule_selector(entry: dict[str, object]) -> list[str]:
    """``ip rule del`` arguments that match exactly this listed rule, not everything at its
    priority: a stale rule goes without taking a fresh one at the same priority with it."""
    selector = ["priority", str(entry.get("priority"))]
    if "fwmark" in entry:
        selector += ["fwmark", str(entry["fwmark"])]
    if "table" in entry:
        selector += ["table", str(entry["table"])]
    return selector


def plan_rules(listing: str, wanted: Collection[Uplink]) -> tuple[list[list[str]], list[Uplink]]:
    """``(rules to delete, uplinks to add)`` from ``ip -j rule show``: exactly one rule per wanted
    uplink at its own priority, nothing at the priorities of the others — the fixed uplinks and
    every country slot, so the rule of a country that left the rules goes too. Adding comes first
    and deleting last, so marked traffic always has its rule (see ``apply_router``)."""
    try:
        entries = json.loads(listing or "[]")
    except json.JSONDecodeError as exc:
        raise RouterError("ip -j rule show returned no JSON") from exc
    by_table = {uplink.table: uplink for uplink in wanted}
    delete: list[list[str]] = []
    add: list[Uplink] = []
    for table in sorted({uplink.table for uplink in (*UPLINKS.values(), *COUNTRY_SLOTS)}):
        needed = by_table.get(table)
        kept = False
        for entry in (item for item in entries if item.get("priority") == table):
            exact = needed is not None and (
                entry.get("fwmark") == hex(needed.mark) and entry.get("table") == str(table)
            )
            if exact and not kept:
                kept = True
            else:
                delete.append(_rule_selector(entry))
        if needed is not None and not kept:
            add.append(needed)
    return delete, add


def add_rules(add: list[Uplink]) -> None:
    for uplink in add:
        _ip(
            [
                "rule", "add", "fwmark", hex(uplink.mark),
                "table", str(uplink.table), "priority", str(uplink.table),
            ]
        )  # fmt: skip


def delete_rules(delete: list[list[str]]) -> None:
    for selector in delete:
        _ip(["rule", "del", *selector])


def last_resort_route(uplink: Uplink) -> list[str]:
    return ["unreachable", "default", "metric", str(LAST_RESORT_METRIC), "table", str(uplink.table)]


def gateway_route(uplink: Uplink) -> list[str]:
    return ["default", "via", uplink.gateway, "dev", UPSTREAMS_BRIDGE, "table", str(uplink.table)]


def set_gateway_route(uplink: Uplink, alive: bool) -> None:
    """Point the uplink table at its gateway while the container answers, withdraw it when it
    does not: then the last-resort route holds the traffic (``failopen: false``) or, without
    one, the lookup falls through to the main table (``failopen: true``)."""
    if alive:
        _ip(["route", "replace", *gateway_route(uplink)])
    else:
        _ip(["route", "del", *gateway_route(uplink)], missing_ok=True)


def apply_router(config: Config) -> list[str]:
    """Render and apply the LAN router; returns the keys of the uplinks in use. The kill switch
    comes first: the last-resort route exists before any rule steers traffic into its table. The
    gateway routes themselves are set by the uplink watchers once the gateways answer."""
    ruleset = router_ruleset(config)
    if ruleset is None:
        remove_router()
        return []
    table = uplink_table(config)
    used = used_uplinks(config)
    check_ruleset(ruleset)
    for key in used:
        if config.routing is not None and not config.routing.failopen:
            _ip(["route", "replace", *last_resort_route(table[key])])
        else:
            _ip(["route", "del", *last_resort_route(table[key])], missing_ok=True)
    # Never a moment when a mark has no rule: the new rule, then the new marks, and only then the
    # rules of the old marks go. Deleting first would send still-marked traffic to the main table.
    delete, add = plan_rules(_ip(["-j", "rule", "show"]), [table[key] for key in used])
    add_rules(add)
    apply_ruleset(ruleset)
    delete_rules(delete)
    in_use = {table[key].table for key in used}
    for uplink in (*UPLINKS.values(), *COUNTRY_SLOTS):
        if uplink.table not in in_use:
            _ip(["route", "flush", "table", str(uplink.table)], missing_ok=True)
    sync_docker_user(router_docker_user_rules(config), ROUTER_COMMENT)
    return used


def remove_router() -> None:
    """Nothing of the LAN router stays: marks, rules, uplink tables, DOCKER-USER transit."""
    _nft(["-f", "-"], ROUTER_TEARDOWN)
    if find_ip() is not None:
        delete_rules(plan_rules(_ip(["-j", "rule", "show"]), ())[0])
        for uplink in (*UPLINKS.values(), *COUNTRY_SLOTS):
            _ip(["route", "flush", "table", str(uplink.table)], missing_ok=True)
    if find_iptables():
        sync_docker_user([], ROUTER_COMMENT)


def apply_firewall(config: Config) -> bool:
    """Render, check and apply the VPS firewall; ``False`` when this configuration has none
    (a leftover table from an earlier configuration is removed then)."""
    ruleset = firewall_ruleset(config)
    if ruleset is None:
        remove_firewall()
        return False
    if not ssh_rule_present(ruleset, config.firewall.ssh_ports):
        raise RouterError("rendered firewall does not open ssh; refusing to apply it")
    check_ruleset(ruleset)
    apply_ruleset(ruleset)
    return True


@dataclass(frozen=True)
class RoutingFacts:
    """The LAN router as the host has it: rules for the uplinks in use, and per uplink its gateway
    route and its kill-switch route."""

    rules_current: bool | None
    gateway_routes: dict[str, bool | None]
    last_resort_routes: dict[str, bool | None]


def read_routing(config: Config) -> RoutingFacts:
    """What the host routes now for the uplinks in use; ``None`` for what could not be read.
    Read-only: ``doctor`` and the ``/status`` of core both use it."""
    ip = find_ip()
    if ip is None:
        return RoutingFacts(None, {}, {})
    try:
        table = uplink_table(config)
        uplinks = used_uplinks(config)
        rules = subprocess.run(
            [ip, "-j", "rule", "show"], check=True, capture_output=True, text=True
        )
        delete, add = plan_rules(rules.stdout, [table[key] for key in uplinks])
    except (OSError, subprocess.CalledProcessError, RouterError):
        return RoutingFacts(None, {}, {})
    gateways: dict[str, bool | None] = {}
    last_resorts: dict[str, bool | None] = {}
    for key in uplinks:
        uplink = table[key]
        try:
            routes = subprocess.run(
                [ip, "-j", "route", "show", "table", str(uplink.table)],
                check=True,
                capture_output=True,
                text=True,
            )
            entries = json.loads(routes.stdout or "[]")
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
            gateways[key] = last_resorts[key] = None
            continue
        gateways[key] = any(entry.get("gateway") == uplink.gateway for entry in entries)
        last_resorts[key] = any(
            entry.get("type") == "unreachable" and entry.get("metric") == LAST_RESORT_METRIC
            for entry in entries
        )
    return RoutingFacts(not delete and not add, gateways, last_resorts)
