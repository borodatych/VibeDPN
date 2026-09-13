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

from vibedpn.config import Config, DevicePolicy, Role, RoutingMode, Upstream, parse_port_range
from vibedpn.detect import SBIN_DIRS
from vibedpn.engine.myst import NODEUI_PORT
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
}
# Device policies that send a device through an uplink.
POLICY_UPLINKS: dict[DevicePolicy, Upstream] = {
    DevicePolicy.VPS: Upstream.VPS,
    DevicePolicy.DPN: Upstream.DPN,
}
# policy block: no ip rule knows this mark, and the forward chain drops it.
BLOCK_MARK = 0x30


def active_uplink(config: Config) -> Upstream | None:
    """The uplink LAN traffic leaves through, or ``None`` when everything goes direct."""
    if config.network is None or config.routing is None:
        return None
    if config.routing.mode is RoutingMode.SMART:
        raise RouterError("routing.mode smart is not implemented yet; use off or full")
    if config.routing.mode is RoutingMode.OFF:
        return None
    return config.routing.default_upstream


def used_uplinks(config: Config) -> list[Upstream]:
    """Every uplink some LAN traffic may take: the one of routing.mode full, and the ones device
    policies name. Each needs its ip rule, its table with the kill switch and a watcher."""
    wanted: set[Upstream] = set()
    active = active_uplink(config)
    if active is not None:
        wanted.add(active)
    if config.network is not None:
        wanted.update(
            POLICY_UPLINKS[device.policy]
            for device in config.devices
            if device.policy in POLICY_UPLINKS
        )
    return [upstream for upstream in UPLINKS if upstream in wanted]


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
            block_mark=hex(BLOCK_MARK),
            uplink_policies=[
                UplinkPolicy(policy.value, hex(UPLINKS[upstream].mark))
                for policy, upstream in POLICY_UPLINKS.items()
            ],
            mode_upstream=active.value if active else "",
            mode_mark=hex(UPLINKS[active].mark) if active else "",
            # The VPS forwards no peer to private ranges (tunnel egress), so the only private
            # target behind the tunnel is the VPS itself: its node panel and core API. Closing
            # the ranges needs no knowledge of the tunnel subnet, which the peer file lacks.
            vps_lan_closed=config.upstreams.vps.enabled and not config.upstreams.vps.lan_access,
            vps_mark=hex(UPLINKS[Upstream.VPS].mark),
            private_ranges=EGRESS_BLOCKED_RANGES,
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


def plan_rules(
    listing: str, wanted: Collection[Upstream]
) -> tuple[list[list[str]], list[Upstream]]:
    """``(rules to delete, uplinks to add)`` from ``ip -j rule show``: exactly one rule per
    active uplink at its own priority, nothing at the priorities of the others. Adding comes
    first and deleting last, so marked traffic always has its rule (see ``apply_router``)."""
    try:
        entries = json.loads(listing or "[]")
    except json.JSONDecodeError as exc:
        raise RouterError("ip -j rule show returned no JSON") from exc
    delete: list[list[str]] = []
    add: list[Upstream] = []
    for upstream, uplink in UPLINKS.items():
        needed = upstream in wanted
        kept = False
        for entry in (item for item in entries if item.get("priority") == uplink.table):
            exact = entry.get("fwmark") == hex(uplink.mark) and entry.get("table") == str(
                uplink.table
            )
            if needed and exact and not kept:
                kept = True
            else:
                delete.append(_rule_selector(entry))
        if needed and not kept:
            add.append(upstream)
    return delete, add


def add_rules(add: list[Upstream]) -> None:
    for upstream in add:
        uplink = UPLINKS[upstream]
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


def set_gateway_route(upstream: Upstream, alive: bool) -> None:
    """Point the uplink table at its gateway while the container answers, withdraw it when it
    does not: then the last-resort route holds the traffic (``failopen: false``) or, without
    one, the lookup falls through to the main table (``failopen: true``)."""
    uplink = UPLINKS[upstream]
    if alive:
        _ip(["route", "replace", *gateway_route(uplink)])
    else:
        _ip(["route", "del", *gateway_route(uplink)], missing_ok=True)


def apply_router(config: Config) -> list[Upstream]:
    """Render and apply the LAN router; returns the uplinks in use. The kill switch comes first:
    the last-resort route exists before any rule steers traffic into its table. The gateway
    routes themselves are set by the uplink watchers once the gateways answer."""
    ruleset = router_ruleset(config)
    if ruleset is None:
        remove_router()
        return []
    used = used_uplinks(config)
    check_ruleset(ruleset)
    for upstream, uplink in UPLINKS.items():
        if upstream not in used:
            continue
        if config.routing is not None and not config.routing.failopen:
            _ip(["route", "replace", *last_resort_route(uplink)])
        else:
            _ip(["route", "del", *last_resort_route(uplink)], missing_ok=True)
    # Never a moment when a mark has no rule: the new rule, then the new marks, and only then the
    # rules of the old marks go. Deleting first would send still-marked traffic to the main table.
    delete, add = plan_rules(_ip(["-j", "rule", "show"]), used)
    add_rules(add)
    apply_ruleset(ruleset)
    delete_rules(delete)
    for upstream, uplink in UPLINKS.items():
        if upstream not in used:
            _ip(["route", "flush", "table", str(uplink.table)], missing_ok=True)
    sync_docker_user(router_docker_user_rules(config), ROUTER_COMMENT)
    return used


def remove_router() -> None:
    """Nothing of the LAN router stays: marks, rules, uplink tables, DOCKER-USER transit."""
    _nft(["-f", "-"], ROUTER_TEARDOWN)
    if find_ip() is not None:
        delete_rules(plan_rules(_ip(["-j", "rule", "show"]), ())[0])
        for uplink in UPLINKS.values():
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
        uplinks = used_uplinks(config)
        rules = subprocess.run(
            [ip, "-j", "rule", "show"], check=True, capture_output=True, text=True
        )
        delete, add = plan_rules(rules.stdout, uplinks)
    except (OSError, subprocess.CalledProcessError, RouterError):
        return RoutingFacts(None, {}, {})
    gateways: dict[str, bool | None] = {}
    last_resorts: dict[str, bool | None] = {}
    for uplink in uplinks:
        try:
            routes = subprocess.run(
                [ip, "-j", "route", "show", "table", str(UPLINKS[uplink].table)],
                check=True,
                capture_output=True,
                text=True,
            )
            entries = json.loads(routes.stdout or "[]")
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
            gateways[uplink.value] = last_resorts[uplink.value] = None
            continue
        gateways[uplink.value] = any(
            entry.get("gateway") == UPLINKS[uplink].gateway for entry in entries
        )
        last_resorts[uplink.value] = any(
            entry.get("type") == "unreachable" and entry.get("metric") == LAST_RESORT_METRIC
            for entry in entries
        )
    return RoutingFacts(not delete and not add, gateways, last_resorts)
