"""Host and box diagnostics for ``vibedpn doctor``: gather facts, evaluate, report — never fix.

``gather`` is the only function with side effects; ``evaluate`` and the parsers are pure and
unit-tested on fixtures. A fact that could not be collected is ``None`` (or carries an error
text) and turns into a ``warn`` that names what to run — never into a false ``ok`` or ``fail``.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from ipaddress import IPv4Address
from pathlib import Path

from vibedpn.bootstrap import (
    ENV_FILE,
    LITE_BELOW_MEMORY_BYTES,
    SECRETS_DIR,
    required_secrets,
    secrets_present,
)
from vibedpn.compose import (
    ComposeError,
    ServiceStatus,
    capture,
    check_box,
    compose_argv,
    parse_ps,
    preflight,
)
from vibedpn.config import (
    Config,
    NetworkMode,
    Profile,
    Role,
    RoutingMode,
    UiVariant,
    Upstream,
    parse_port_range,
)
from vibedpn.detect import (
    SSHD,
    WIREGUARD_MODULE,
    HostProbe,
    is_wireless,
    module_present,
    parse_interface,
)
from vibedpn.engine.myst import (
    NAT_OPEN,
    NAT_PUNCHABLE,
    NAT_SYMMETRIC,
    NODEUI_PORT,
    TEQUILAPI_PORT,
    MystError,
    TequilaClient,
    nat_type,
)
from vibedpn.engine.resolver import RESOLVER_HOST, RESOLVER_PORT
from vibedpn.engine.router import (
    EGRESS_COMMENT,
    EGRESS_TABLE,
    NFT_TABLE,
    ROUTER_COMMENT,
    ROUTER_TABLE,
    UPSTREAMS_BRIDGE,
    RouterError,
    docker_user_chain,
    docker_user_rules,
    find_ip,
    find_nft,
    plan_docker_user,
    read_routing,
    router_docker_user_rules,
    uplink_service,
    uplink_table,
    used_uplinks,
)
from vibedpn.engine.wg import SERVER_CONF_FILE, SERVER_KEY_FILE, server_address
from vibedpn.engine.wg import SERVER_DIR as WG_SERVER_DIR

NFTABLES_MODULE = "nf_tables"
IP_FORWARD_SYSCTL = Path("/proc/sys/net/ipv4/ip_forward")
SS_ARGV = ["ss", "-H", "-lntup"]
API_HOST = "127.0.0.1"
DNS_PORT = 53
DNS_UPLINK_CHAIN = "dns_uplink"  # templates/lan-router.nft.j2
DHCP_SERVER_PORT = 67
CORE_PROCESS_NAMES = frozenset({"vibedpn-core"})  # comm of the console script in `ss -p`
ANY_ADDRESSES = frozenset({"0.0.0.0", "*", "::", "[::]"})
WILDCARD = "*"
RUNNING_STATE = "running"
NEVER_STARTED_STATE = "created"
SUDO_HINT = "sudo vibedpn doctor"
# `doctor --network` asks a third party for the public address; the service logs nothing
# (https://www.ipify.org/). The environment variable points a test stand at its own echo server.
EXIT_IP_URL = "https://api.ipify.org"
EXIT_IP_URL_ENV = "VIBEDPN_EXIT_IP_URL"
EXIT_IP_TIMEOUT_SECONDS = 8
DIRECT_EXIT = "direct"
# The gateway container of each uplink; both images carry busybox wget with TLS (verified).
UPLINK_SERVICES = {Upstream.VPS: "wg-client", Upstream.DPN: "myst-consumer"}
STRICT_RP_FILTER = 1

DEFAULT_HTTP_PORT = 80


class Verdict(StrEnum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True)
class CheckResult:
    name: str
    verdict: Verdict
    detail: str
    hint: str = ""


@dataclass(frozen=True)
class FileFact:
    present: bool | None  # None: cannot stat (root-only directory, not root)
    mode: int | None = None


@dataclass(frozen=True)
class Listener:
    proto: str
    address: str
    port: int
    process: str  # empty when ``ss`` could not tell (not root)


@dataclass(frozen=True)
class PortNeed:
    """A port (or range) a service of this box must be able to bind."""

    service: str
    proto: str
    address: str  # a concrete address or WILDCARD
    port: int
    port_end: int | None = None

    @property
    def label(self) -> str:
        span = f"{self.port}-{self.port_end}" if self.port_end else str(self.port)
        return f"{self.proto}/{span}"

    def covers(self, port: int) -> bool:
        return self.port <= port <= (self.port_end or self.port)


@dataclass(frozen=True)
class ExitFact:
    """The public address seen from one path: the host itself, or inside an uplink gateway."""

    name: str  # DIRECT_EXIT or an uplink
    address: str | None
    error: str = ""


@dataclass(frozen=True)
class DoctorFacts:
    config: Config | None
    config_error: str
    config_hint: str
    env_current: bool | None  # None: no .env yet
    secrets: dict[str, bool | None]  # None per file: cannot stat (root-only dir, not root)
    wireguard: bool | None  # None: could not check
    nf_tables: bool | None
    ip_forward: bool | None  # None: unreadable
    listeners: list[Listener] | None  # None: ss unavailable, see listeners_error
    is_root: bool
    docker_error: str
    listeners_error: str = ""
    services: list[ServiceStatus] = field(default_factory=list)
    active_services: list[str] = field(default_factory=list)
    firewall_table: bool | None = None  # None: could not list tables, see firewall_error
    firewall_error: str = ""
    tunnel: dict[str, FileFact] = field(default_factory=dict)  # role vps: files core renders
    egress_table: bool | None = None  # None: could not list tables, see egress_error
    egress_error: str = ""
    docker_user: bool | None = None  # True: rules current or no DOCKER-USER; None: see error
    docker_user_error: str = ""
    router_table: bool | None = None  # roles with a LAN; None: see router_error
    dns_uplink: bool | None = None  # chain dns_uplink loaded (AdGuard through the uplink)
    router_error: str = ""
    router_rules: bool | None = None  # ip rule matches routing.mode
    router_docker_user: bool | None = None
    router_docker_user_error: str = ""
    # Per uplink in use: its gateway route, and its kill-switch route; None: not readable.
    uplink_routes: dict[str, bool | None] = field(default_factory=dict)
    last_resort_routes: dict[str, bool | None] = field(default_factory=dict)
    rp_filter: int | None = None  # max of all and the gateway bridge, as the kernel uses it
    lan_ipv6: bool | None = None  # a global IPv6 address on lan_interface; None: not checked
    exits: list[ExitFact] | None = None  # None: `doctor` ran without --network
    memory_bytes: int | None = None  # None: /proc/meminfo could not be read
    # The node's NAT type (only with --network: the node asks Mysterium's servers); "" not asked.
    nat: str = ""
    nat_error: str = ""
    # gateway mode: whether lan_address is configured on lan_interface; None: not checked
    lan_address_set: bool | None = None
    lan_wireless: bool | None = None  # network.wifi: lan_interface is a radio


def parse_ss(output: str) -> list[Listener]:
    """Listeners from ``ss -H -lntup``: ``proto state recvq sendq local peer [users:(...)]``."""
    listeners = []
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 5:  # noqa: PLR2004 - proto, state, two queues, local address
            continue
        proto, local = fields[0], fields[4]
        address, _, port_text = local.rpartition(":")
        if not port_text.isdigit():
            continue
        address = address.split("%")[0].strip("[]") or WILDCARD
        process = ""
        if "users:((" in line:
            process = line.split('users:(("', 1)[1].split('"', 1)[0]
        listeners.append(Listener(proto, address, int(port_text), process))
    return listeners


def parse_sysctl_flag(text: str) -> bool | None:
    value = text.strip()
    if value not in {"0", "1"}:
        return None
    return value == "1"


def port_needs(config: Config) -> list[PortNeed]:
    needs = [PortNeed("core", "tcp", API_HOST, config.api.port)]
    if config.network is not None:
        lan = str(config.network.lan_address)
        if config.dns.enabled:
            needs += [
                PortNeed("adguard", "udp", lan, DNS_PORT),
                PortNeed("adguard", "tcp", lan, DNS_PORT),
                PortNeed("adguard", "tcp", lan, config.dns.web_port),
                PortNeed("core", "udp", RESOLVER_HOST, RESOLVER_PORT),
            ]
        if config.ui.enabled:
            needs.append(PortNeed("ui", "tcp", lan, config.ui.port))
    if config.provider.enabled:
        start, end = parse_port_range(config.provider.udp_ports)
        needs += [
            PortNeed("myst-provider", "tcp", API_HOST, NODEUI_PORT),
            PortNeed("myst-provider", "tcp", API_HOST, TEQUILAPI_PORT),
            PortNeed("myst-provider", "udp", WILDCARD, start, end),
        ]
    if config.wg_server is not None:
        needs.append(PortNeed("wg-server", "udp", WILDCARD, config.wg_server.listen_port))
    if config.network is not None and config.network.mode is NetworkMode.GATEWAY:
        needs.append(PortNeed("dnsmasq", "udp", WILDCARD, DHCP_SERVER_PORT))
    return needs


def holder_of(need: PortNeed, listeners: list[Listener]) -> Listener | None:
    """The listener that would collide with ``need``, if any."""
    for listener in listeners:
        if listener.proto != need.proto or not need.covers(listener.port):
            continue
        overlap = (
            need.address == WILDCARD
            or listener.address in ANY_ADDRESSES
            or listener.address == need.address
        )
        if overlap:
            return listener
    return None


def wireguard_required(config: Config) -> bool:
    """Only the WireGuard containers use the host module; myst brings its own tunnel."""
    profiles = set(config.compose_profiles())
    return Profile.WG_SERVER in profiles or Profile.WG_CLIENT in profiles


def evaluate(facts: DoctorFacts) -> list[CheckResult]:
    results: list[CheckResult] = []
    config = facts.config
    if config is None:
        results.append(CheckResult("config", Verdict.FAIL, facts.config_error, facts.config_hint))
    else:
        profiles = ",".join(profile.value for profile in config.compose_profiles())
        results.append(
            CheckResult("config", Verdict.OK, f"role {config.role.value}, profiles {profiles}")
        )
        results.append(_env_result(facts.env_current))
        results.append(_secrets_result(config, facts.secrets))
    results.append(_wireguard_result(config, facts.wireguard))
    results.append(
        _module_result("nf_tables", facts.nf_tables, "the router engine and Docker need it")
    )
    results.append(_ip_forward_result(facts.ip_forward))
    if config is not None and config.role is Role.VPS:
        results.extend(_firewall_results(config, facts))
        if facts.tunnel:
            results.append(_tunnel_result(facts.tunnel))
        access = _tunnel_access_result(config, facts)
        if access is not None:
            results.append(access)
        if config.wg_server is not None:
            results.append(_egress_result(config, facts))
    if config is not None and config.network is not None:
        results.extend(_lan_results(config, facts))
    results.extend(_nat_results(facts))
    results.extend(_gateway_results(facts))
    results.extend(_wifi_results(facts))
    if facts.docker_error:
        results.append(CheckResult("docker", Verdict.FAIL, facts.docker_error))
    else:
        results.append(CheckResult("docker", Verdict.OK, "daemon reachable"))
    if config is not None:
        results.extend(_port_results(config, facts))
        if not facts.docker_error:
            results.extend(_service_results(facts))
    return results


def _env_result(env_current: bool | None) -> CheckResult:
    if env_current is None:
        return CheckResult("env", Verdict.WARN, ".env not written yet", "vibedpn up")
    if not env_current:
        return CheckResult("env", Verdict.WARN, ".env is behind config.yaml", "vibedpn up")
    return CheckResult("env", Verdict.OK, ".env matches config.yaml")


def _secrets_result(config: Config, secrets: dict[str, bool | None]) -> CheckResult:
    needed = required_secrets(config)
    missing = [name for name in needed if secrets.get(name) is False]
    if missing:
        return CheckResult(
            "secrets", Verdict.FAIL, f"missing {', '.join(missing)}", "vibedpn init --force"
        )
    unknown = [name for name in needed if secrets.get(name) is None]
    if unknown:
        return CheckResult(
            "secrets",
            Verdict.WARN,
            f"cannot check {', '.join(unknown)} ({SECRETS_DIR}/ is root-only)",
            SUDO_HINT,
        )
    return CheckResult("secrets", Verdict.OK, ", ".join(needed))


def _module_result(name: str, present: bool | None, why: str) -> CheckResult:
    if present is None:
        return CheckResult(
            name, Verdict.WARN, "cannot tell: modprobe not found on this PATH", SUDO_HINT
        )
    if present:
        return CheckResult(name, Verdict.OK, "kernel module available")
    return CheckResult(name, Verdict.FAIL, f"kernel module missing; {why}")


def _wireguard_result(config: Config | None, present: bool | None) -> CheckResult:
    if present is None or present:
        return _module_result("wireguard", present, "")
    if config is not None and wireguard_required(config):
        return CheckResult(
            "wireguard",
            Verdict.FAIL,
            "kernel module missing; tunnels cannot start",
            "use a stock Debian 12/13 or Raspberry Pi OS kernel (wireguard is built in)",
        )
    return CheckResult(
        "wireguard",
        Verdict.WARN,
        "kernel module missing; this role runs no WireGuard container (myst brings its own tunnel)",
    )


def _tunnel_result(files: dict[str, FileFact]) -> CheckResult:
    """The server key and wg0.conf that core writes at start: present and closed to others."""
    names = ", ".join(files) or "tunnel files"
    if any(fact.present is None for fact in files.values()):
        return CheckResult(
            "tunnel", Verdict.WARN, f"cannot check {names} ({SECRETS_DIR}/ is root-only)", SUDO_HINT
        )
    missing = [name for name, fact in files.items() if not fact.present]
    if missing:
        return CheckResult(
            "tunnel",
            Verdict.WARN,
            f"{', '.join(missing)} not written yet; core creates them at start",
            "vibedpn up",
        )
    loose = [name for name, fact in files.items() if fact.mode is not None and fact.mode & 0o077]
    if loose:
        return CheckResult(
            "tunnel",
            Verdict.FAIL,
            f"{', '.join(loose)} readable by other users",
            "vibedpn restart (core resets the mode to 600)",
        )
    return CheckResult("tunnel", Verdict.OK, f"{names} in {SECRETS_DIR}/{WG_SERVER_DIR}, mode 600")


def _tunnel_access_result(config: Config, facts: DoctorFacts) -> CheckResult | None:
    """Core itself listens on the tunnel address: the node panel and the API for home boxes."""
    if config.wg_server is None:
        return None
    address = str(server_address(config).ip)
    if facts.listeners is None:
        return CheckResult("tunnel access", Verdict.WARN, f"cannot check: {facts.listeners_error}")
    problems: list[str] = []
    for port in (NODEUI_PORT, config.api.port):
        holder = next(
            (
                item
                for item in facts.listeners
                if item.proto == "tcp" and item.address == address and item.port == port
            ),
            None,
        )
        if holder is None:
            problems.append(f"nothing listens on {address}:{port}")
        elif holder.process and holder.process not in CORE_PROCESS_NAMES:
            problems.append(f"{address}:{port} is held by {holder.process}, not core")
    if problems:
        return CheckResult(
            "tunnel access",
            Verdict.FAIL,
            "; ".join(problems),
            "vibedpn restart, then vibedpn logs core",
        )
    return CheckResult(
        "tunnel access",
        Verdict.OK,
        f"node panel {address}:{NODEUI_PORT} and core API {address}:{config.api.port}"
        " for home boxes",
    )


def _firewall_results(config: Config, facts: DoctorFacts) -> list[CheckResult]:
    """The table must match ``firewall.enabled``, and sshd must fit through it."""
    present = facts.firewall_table
    if not config.firewall.enabled:
        if present:
            return [
                CheckResult(
                    "firewall",
                    Verdict.WARN,
                    f"firewall.enabled is false but table {NFT_TABLE} is still loaded",
                    "vibedpn restart (core removes it at start)",
                )
            ]
        if present is None:
            return []
        return [CheckResult("firewall", Verdict.OK, "disabled in config.yaml, no table loaded")]
    if present is None:
        hint = "" if facts.is_root else SUDO_HINT  # as root the reason names the fix itself
        return [CheckResult("firewall", Verdict.WARN, facts.firewall_error, hint)]
    if not present:
        return [
            CheckResult(
                "firewall",
                Verdict.FAIL,
                f"table {NFT_TABLE} is not loaded; core applies it at start",
                "vibedpn up, then vibedpn logs core",
            )
        ]
    results = [CheckResult("firewall", Verdict.OK, f"table {NFT_TABLE} is loaded")]
    ssh = _ssh_result(config.firewall.ssh_ports, facts.listeners)
    if ssh is not None:
        results.append(ssh)
    return results


def _egress_result(config: Config, facts: DoctorFacts) -> CheckResult:
    """Peers reach the internet only with both the NAT table and an opened Docker forward drop."""
    hint = "" if facts.is_root else SUDO_HINT
    subnet = config.wg_server.subnet if config.wg_server else ""
    if facts.egress_table is None:
        return CheckResult("tunnel egress", Verdict.WARN, facts.egress_error, hint)
    if not facts.egress_table:
        return CheckResult(
            "tunnel egress",
            Verdict.FAIL,
            f"table {EGRESS_TABLE} is not loaded for {subnet}: peers cannot reach the internet",
            "vibedpn restart, then vibedpn logs core",
        )
    if facts.docker_user is None:
        return CheckResult("tunnel egress", Verdict.WARN, facts.docker_user_error, hint)
    if not facts.docker_user:
        return CheckResult(
            "tunnel egress",
            Verdict.FAIL,
            "Docker drops forwarded traffic and DOCKER-USER does not let the tunnel out",
            "vibedpn restart (core adds the rules at start), then vibedpn logs core",
        )
    return CheckResult("tunnel egress", Verdict.OK, f"peers of {subnet} leave through this VPS")


def _router_result(config: Config, facts: DoctorFacts) -> CheckResult:  # noqa: PLR0911 - a verdict per fact, in order
    """The LAN router is loaded as config.yaml says, and every uplink in use has its gateway."""
    hint = "" if facts.is_root else SUDO_HINT
    restart = "vibedpn restart, then vibedpn logs core"
    try:
        uplinks = used_uplinks(config)
    except RouterError as exc:
        return CheckResult("router", Verdict.FAIL, str(exc), "set routing.mode in config.yaml")
    if facts.router_table is None:
        return CheckResult("router", Verdict.WARN, facts.router_error, hint)
    if not facts.router_table:
        return CheckResult("router", Verdict.FAIL, f"table {ROUTER_TABLE} is not loaded", restart)
    if facts.router_rules is None or facts.router_docker_user is None:
        detail = facts.router_docker_user_error or "cannot read ip rules"
        return CheckResult("router", Verdict.WARN, detail, hint)
    if not facts.router_rules:
        return CheckResult("router", Verdict.FAIL, "ip rules do not match config.yaml", restart)
    if facts.rp_filter == STRICT_RP_FILTER:
        return CheckResult(
            "router",
            Verdict.FAIL,
            f"rp_filter is strict (1): replies from the gateways on {UPSTREAMS_BRIDGE} are dropped",
            f"sysctl -w net.ipv4.conf.all.rp_filter=2 net.ipv4.conf.{UPSTREAMS_BRIDGE}.rp_filter=2"
            " and persist it in /etc/sysctl.d/",
        )
    if not facts.router_docker_user:
        return CheckResult(
            "router",
            Verdict.FAIL,
            "Docker drops forwarded LAN traffic and DOCKER-USER does not let it through",
            restart,
        )
    mode = config.routing.mode.value if config.routing is not None else "off"
    if not uplinks:
        return CheckResult(
            "router", Verdict.OK, f"routing.mode {mode}: LAN goes direct through the box"
        )
    failopen = config.routing is not None and config.routing.failopen
    known = uplink_table(config)
    for uplink in uplinks:
        table = known[uplink].table
        gateway = facts.uplink_routes.get(uplink)
        last_resort = facts.last_resort_routes.get(uplink)
        if gateway is None or (not failopen and last_resort is None):
            return CheckResult("router", Verdict.WARN, f"cannot read routing table {table}", hint)
        if not failopen and not last_resort:
            return CheckResult(
                "router",
                Verdict.FAIL,
                f"routing table {table} has no kill-switch route:"
                " a dead gateway would leak LAN traffic",
                restart,
            )
        if not gateway:
            fate = (
                "traffic goes direct (failopen: true)"
                if failopen
                else "its traffic is held (kill switch)"
            )
            return CheckResult(
                "router",
                Verdict.WARN,
                f"uplink {uplink} gateway {known[uplink].gateway} does not answer; {fate}",
                f"vibedpn logs {uplink_service(uplink)}",
            )
    in_use = ", ".join(f"{uplink} ({known[uplink].gateway})" for uplink in uplinks)
    return CheckResult("router", Verdict.OK, f"routing.mode {mode}, uplinks in use: {in_use}")


def _lan_results(config: Config, facts: DoctorFacts) -> list[CheckResult]:
    """Checks of a box that routes a LAN: the router, IPv6 around it, and — with --network —
    where its traffic really leaves."""
    results = [_router_result(config, facts)]
    ipv6 = _lan_ipv6_result(config, facts)
    if ipv6 is not None:
        results.append(ipv6)
    if config.upstreams.vps.enabled:
        results.append(_vps_lan_access_result(config))
    if config.ui.enabled:
        results.append(_ui_name_result(config))
        variant = _ui_variant_result(config, facts.memory_bytes)
        if variant is not None:
            results.append(variant)
    if facts.exits is not None:
        results.extend(_exit_results(config, facts.exits, facts.dns_uplink))
    return results


def _vps_lan_access_result(config: Config) -> CheckResult:
    """Informational: whether LAN devices reach the node panel and core API of the VPS."""
    if config.upstreams.vps.lan_access:
        return CheckResult(
            "vps lan access",
            Verdict.OK,
            "open: LAN devices reach the node panel and core API of the VPS through the tunnel",
        )
    return CheckResult(
        "vps lan access",
        Verdict.OK,
        "closed: LAN devices reach no private address through the tunnel",
    )


def _ui_variant_result(config: Config, memory: int | None) -> CheckResult | None:
    """A full panel on a small host swaps or is killed; lite on a big one only costs screens."""
    if memory is None:
        return None
    size = f"{memory / 1024**3:.1f} GiB"
    if config.ui.variant is UiVariant.FULL and memory < LITE_BELOW_MEMORY_BYTES:
        return CheckResult(
            "ui variant",
            Verdict.WARN,
            f"ui.variant full on a host with {size}",
            "set ui.variant: lite in config.yaml, then vibedpn up",
        )
    return CheckResult("ui variant", Verdict.OK, f"{config.ui.variant.value} on a host with {size}")


def _ui_name_result(config: Config) -> CheckResult:
    """The panel by name works only where AdGuard answers it; the address always works."""
    network = config.network
    address = network.lan_address if network is not None else None
    port = "" if config.ui.port == DEFAULT_HTTP_PORT else f":{config.ui.port}"
    if not config.dns.enabled:
        return CheckResult(
            "ui name",
            Verdict.WARN,
            f"{config.ui.host_name} is not published: dns is off",
            f"open http://{address}{port}, or point {config.ui.host_name} at {address}"
            " in the router's DNS",
        )
    return CheckResult(
        "ui name",
        Verdict.OK,
        f"http://{config.ui.host_name}{port} -> {address} (devices using the box as DNS)",
    )


def parse_exit_address(text: str) -> str | None:
    """The IPv4 address an echo service answered with, or ``None`` for anything else."""
    try:
        return str(IPv4Address(text.strip()))
    except ValueError:
        return None


def _exit_results(
    config: Config, exits: list[ExitFact], dns_uplink: bool | None
) -> list[CheckResult]:
    """An uplink that answers with the direct address carries nothing through its tunnel."""
    direct = next((item for item in exits if item.name == DIRECT_EXIT), None)
    results = []
    if direct is not None:
        if direct.address is None:
            results.append(
                CheckResult(
                    "exit direct",
                    Verdict.WARN,
                    f"no public address from the host: {direct.error}",
                    "check the internet connection of the box",
                )
            )
        else:
            results.append(CheckResult("exit direct", Verdict.OK, direct.address))
    for item in exits:
        if item.name == DIRECT_EXIT:
            continue
        name = f"exit {item.name}"
        service = UPLINK_SERVICES[Upstream(item.name)]
        if item.address is None:
            results.append(
                CheckResult(
                    name,
                    Verdict.FAIL,
                    f"no public address through uplink {item.name}: {item.error}",
                    f"vibedpn logs {service}",
                )
            )
        elif direct is not None and item.address == direct.address:
            results.append(
                CheckResult(
                    name,
                    Verdict.FAIL,
                    f"uplink {item.name} leaves with the direct address {item.address}",
                    f"its traffic bypasses the tunnel; vibedpn logs {service}",
                )
            )
        else:
            results.append(CheckResult(name, Verdict.OK, item.address))
    if config.routing is not None and config.dns.enabled:
        if config.routing.mode is RoutingMode.FULL:
            results.append(_dns_leak_result(config, dns_uplink))
        else:
            results.append(
                CheckResult("dns leak", Verdict.OK, "routing.mode off: DNS goes direct by design")
            )
    return results


def _lan_ipv6_result(config: Config, facts: DoctorFacts) -> CheckResult | None:
    """In full, IPv6 from the main router's RA takes the devices around the box: the uplinks
    are IPv4 and the box is not their IPv6 router. AdGuard answers AAAA empty, but addresses
    typed in or cached still go direct."""
    if config.network is None or config.routing is None:
        return None
    if config.routing.mode is not RoutingMode.FULL:
        return None
    lan = config.network.lan_interface
    if facts.lan_ipv6 is None:
        return CheckResult("ipv6", Verdict.WARN, f"cannot read IPv6 addresses of {lan}")
    if facts.lan_ipv6:
        return CheckResult(
            "ipv6",
            Verdict.WARN,
            f"{lan} has a global IPv6 address: devices can reach the internet over IPv6 around the"
            " uplink",
            "turn off IPv6 (RA/DHCPv6) for the LAN on the main router",
        )
    return CheckResult(
        "ipv6", Verdict.OK, f"no global IPv6 on {lan}: routing.mode full covers the LAN"
    )


def parse_global_ipv6(listing: str) -> bool | None:
    """Whether ``ip -j -6 addr show dev <lan>`` lists an address of scope global."""
    try:
        interfaces = json.loads(listing or "[]")
    except json.JSONDecodeError:
        return None
    return any(
        info.get("family") == "inet6" and info.get("scope") == "global"
        for interface in interfaces
        for info in interface.get("addr_info", [])
    )


def _ssh_result(ssh_ports: list[int], listeners: list[Listener] | None) -> CheckResult | None:
    """Every port sshd actually listens on must be in ``firewall.ssh_ports``; the config-file
    reading of ``init`` is not the daemon (socket activation, a later edit), so ``ss`` decides."""
    if listeners is None:
        return None
    listening = sorted(
        {item.port for item in listeners if item.process == SSHD and item.proto == "tcp"}
    )
    if not listening:
        return None
    missing = ", ".join(str(port) for port in listening if port not in ssh_ports)
    if missing:
        return CheckResult(
            "ssh",
            Verdict.FAIL,
            f"sshd listens on {missing}, which firewall.ssh_ports does not open",
            "add the port to firewall.ssh_ports in config.yaml, then vibedpn up",
        )
    heard = ", ".join(str(port) for port in listening)
    return CheckResult("ssh", Verdict.OK, f"sshd listens on {heard}, open in the firewall")


def _ip_forward_result(ip_forward: bool | None) -> CheckResult:
    if ip_forward is None:
        return CheckResult("ip_forward", Verdict.WARN, f"cannot read {IP_FORWARD_SYSCTL}")
    if ip_forward:
        return CheckResult("ip_forward", Verdict.OK, "net.ipv4.ip_forward=1")
    return CheckResult(
        "ip_forward",
        Verdict.FAIL,
        "net.ipv4.ip_forward=0; Docker normally enables it at start",
        "sysctl -w net.ipv4.ip_forward=1 and persist it in /etc/sysctl.d/",
    )


def _port_results(config: Config, facts: DoctorFacts) -> list[CheckResult]:
    if facts.listeners is None:
        return [
            CheckResult(
                f"port {need.label}", Verdict.WARN, f"cannot check: {facts.listeners_error}"
            )
            for need in port_needs(config)
        ]
    services_known = not facts.docker_error
    running = {item.service for item in facts.services if item.state == RUNNING_STATE}
    results = []
    for need in port_needs(config):
        name = f"port {need.label}"
        holder = holder_of(need, facts.listeners)
        if holder is None:
            results.append(CheckResult(name, Verdict.OK, f"free for {need.service}"))
            continue
        who = holder.process or (
            "unknown process" + ("" if facts.is_root else "; run with sudo to see it")
        )
        if services_known and need.service in running:
            results.append(CheckResult(name, Verdict.OK, f"held by our {need.service}"))
        elif not services_known:
            results.append(
                CheckResult(
                    name,
                    Verdict.WARN,
                    f"held by {who} on {holder.address}; cannot tell whether it is our"
                    f" {need.service} until Docker is reachable",
                )
            )
        else:
            results.append(
                CheckResult(
                    name,
                    Verdict.FAIL,
                    f"taken by {who} on {holder.address}, needed by {need.service}",
                    "stop that service or change the port in config.yaml",
                )
            )
    return results


def _service_results(facts: DoctorFacts) -> list[CheckResult]:
    by_name = {item.service: item for item in facts.services}
    unhealthy = [name for name, item in by_name.items() if item.health == "unhealthy"]
    not_started: list[str] = []
    broken: list[str] = []
    for name in facts.active_services:
        item = by_name.get(name)
        if item is None or item.state == NEVER_STARTED_STATE:
            not_started.append(name)
        elif item.state != RUNNING_STATE:
            broken.append(f"{name} ({item.status or item.state})")
    if unhealthy or broken:
        detail = "; ".join(
            part
            for part in (
                f"unhealthy: {', '.join(unhealthy)}" if unhealthy else "",
                f"not running: {', '.join(broken)}" if broken else "",
            )
            if part
        )
        return [CheckResult("services", Verdict.FAIL, detail, "vibedpn logs <service>")]
    if not_started:
        return [
            CheckResult(
                "services", Verdict.WARN, f"not started: {', '.join(not_started)}", "vibedpn up"
            )
        ]
    return [CheckResult("services", Verdict.OK, f"{len(facts.active_services)} running")]


def gather(box_dir: Path, *, network: bool = False) -> DoctorFacts:
    """Collect every fact the checks need; failures become facts, not exceptions. Only
    ``network`` makes requests to the internet (the exit-address service)."""
    config: Config | None = None
    config_error = config_hint = ""
    try:
        config = check_box(box_dir)
    except ComposeError as exc:
        config_error, config_hint = exc.message, exc.hint
    env_current: bool | None = None
    env_path = box_dir / ENV_FILE
    if config is not None and env_path.is_file():
        env_current = _env_matches(env_path, config)
    docker_error = ""
    try:
        preflight()
    except ComposeError as exc:
        docker_error = str(exc)
    services: list[ServiceStatus] = []
    active: list[str] = []
    if config is not None and not docker_error:
        try:
            services = parse_ps(capture(compose_argv(box_dir, "ps", "-a", "--format", "json")))
            active = [
                line.strip()
                for line in capture(compose_argv(box_dir, "config", "--services")).splitlines()
                if line.strip()
            ]
        except ComposeError as exc:
            docker_error = str(exc)
    listeners, listeners_error = _listeners()
    firewall_table, firewall_error = None, ""
    tunnel: dict[str, FileFact] = {}
    egress_table, egress_error = None, ""
    docker_user, docker_user_error = None, ""
    if config is not None and config.role is Role.VPS:
        firewall_table, firewall_error = _table_present(NFT_TABLE)
        tunnel = tunnel_files(box_dir)
        if config.wg_server is not None:
            egress_table, egress_error = _egress_table_current(str(config.wg_server.subnet))
            docker_user, docker_user_error = _docker_user_current(
                docker_user_rules(config), EGRESS_COMMENT
            )
    router_table, router_error = None, ""
    router_rules: bool | None = None
    uplink_routes: dict[str, bool | None] = {}
    last_resort_routes: dict[str, bool | None] = {}
    lan_ipv6: bool | None = None
    rp_filter = None
    router_docker_user, router_docker_user_error = None, ""
    if config is not None and config.network is not None:
        router_table, router_error = _table_present(ROUTER_TABLE)
        routing = read_routing(config)
        router_rules, uplink_routes, last_resort_routes = (
            routing.rules_current,
            routing.gateway_routes,
            routing.last_resort_routes,
        )
        rp_filter = _read_rp_filter()
        router_docker_user, router_docker_user_error = _docker_user_current(
            router_docker_user_rules(config), ROUTER_COMMENT
        )
        lan_ipv6 = _read_lan_ipv6(config.network.lan_interface)
    return DoctorFacts(
        config=config,
        config_error=config_error,
        config_hint=config_hint,
        env_current=env_current,
        secrets=secrets_present(box_dir),
        wireguard=module_present(WIREGUARD_MODULE),
        nf_tables=module_present(NFTABLES_MODULE),
        ip_forward=_read_ip_forward(),
        listeners=listeners,
        is_root=os.geteuid() == 0,
        docker_error=docker_error,
        listeners_error=listeners_error,
        services=services,
        active_services=active,
        firewall_table=firewall_table,
        firewall_error=firewall_error,
        tunnel=tunnel,
        egress_table=egress_table,
        egress_error=egress_error,
        docker_user=docker_user,
        docker_user_error=docker_user_error,
        router_table=router_table,
        dns_uplink=_chain_present(ROUTER_TABLE, DNS_UPLINK_CHAIN) if router_table else None,
        router_error=router_error,
        router_rules=router_rules,
        router_docker_user=router_docker_user,
        router_docker_user_error=router_docker_user_error,
        uplink_routes=uplink_routes,
        last_resort_routes=last_resort_routes,
        rp_filter=rp_filter,
        lan_ipv6=lan_ipv6,
        exits=_exits(box_dir, config, services) if network and config is not None else None,
        memory_bytes=HostProbe().memory_bytes(),
        **_nat_facts(config, network=network),
        lan_address_set=_lan_address_set(config),
        lan_wireless=_lan_wireless(config),
    )


def tunnel_files(box_dir: Path) -> dict[str, FileFact]:
    directory = box_dir / SECRETS_DIR / WG_SERVER_DIR
    facts: dict[str, FileFact] = {}
    for name in (SERVER_KEY_FILE, SERVER_CONF_FILE):
        try:
            mode = (directory / name).stat().st_mode & 0o777
        except FileNotFoundError:
            facts[name] = FileFact(present=False)
        except OSError:
            facts[name] = FileFact(present=None)
        else:
            facts[name] = FileFact(present=True, mode=mode)
    return facts


def _docker_user_current(rules: list[list[str]], comment: str) -> tuple[bool | None, str]:
    """Whether ``DOCKER-USER`` already holds exactly this group of ours (or does not exist)."""
    if os.geteuid() != 0:
        return None, "cannot read DOCKER-USER without root"
    try:
        found = docker_user_chain()
    except RouterError as exc:
        return None, str(exc)
    if found is None:
        return True, ""
    delete, insert = plan_docker_user(found[1], rules, comment)
    return not delete and not insert, ""


def _egress_table_current(subnet: str) -> tuple[bool | None, str]:
    """The egress table is loaded *for this subnet*: a changed ``wg_server.subnet`` without a
    restart leaves NAT of the old one, which a mere presence check would call fine."""
    present, error = _table_present(EGRESS_TABLE)
    if not present:
        return present, error
    nft = find_nft()
    if nft is None:
        return None, "nft not found on the host (apt install nftables)"
    try:
        listing = subprocess.run(
            [nft, "list", "table", *EGRESS_TABLE.split()],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return None, f"cannot run nft: {exc.strerror}"
    if listing.returncode != 0:
        return None, f"nft cannot list {EGRESS_TABLE}: {listing.stderr.strip()}"
    return f"ip saddr {subnet} " in listing.stdout, ""


def _exits(box_dir: Path, config: Config, services: list[ServiceStatus]) -> list[ExitFact] | None:
    if config.network is None:
        return None
    url = os.environ.get(EXIT_IP_URL_ENV, EXIT_IP_URL)
    exits = [_direct_exit(url)]
    running = {item.service for item in services if item.state == RUNNING_STATE}
    for upstream in (Upstream.VPS, Upstream.DPN):
        if not config.upstreams.is_enabled(upstream):
            continue
        service = UPLINK_SERVICES[upstream]
        if service not in running:
            exits.append(ExitFact(upstream.value, None, f"{service} is not running"))
            continue
        argv = compose_argv(
            box_dir, "exec", "-T", service,
            "wget", "-qO-", "-T", str(EXIT_IP_TIMEOUT_SECONDS), url,
        )  # fmt: skip
        try:
            answer = capture(argv)
        except ComposeError as exc:
            exits.append(ExitFact(upstream.value, None, str(exc) or "no answer"))
            continue
        address = parse_exit_address(answer)
        error = "" if address else f"unexpected answer {answer.strip()[:40]!r}"
        exits.append(ExitFact(upstream.value, address, error))
    return exits


def _direct_exit(url: str) -> ExitFact:
    try:
        with urllib.request.urlopen(url, timeout=EXIT_IP_TIMEOUT_SECONDS) as response:
            answer = response.read(64).decode("ascii", "replace")
    except (OSError, ValueError) as exc:
        return ExitFact(DIRECT_EXIT, None, str(getattr(exc, "reason", exc)))
    address = parse_exit_address(answer)
    return ExitFact(DIRECT_EXIT, address, "" if address else f"unexpected answer {answer[:40]!r}")


def _read_lan_ipv6(interface: str) -> bool | None:
    ip = find_ip()
    if ip is None:
        return None
    try:
        listing = subprocess.run(
            [ip, "-j", "-6", "addr", "show", "dev", interface],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return parse_global_ipv6(listing.stdout)


def _read_rp_filter() -> int | None:
    """The kernel validates with the max of ``all`` and the interface (ip-sysctl.rst)."""
    values = []
    for name in ("all", UPSTREAMS_BRIDGE):
        try:
            values.append(int(Path(f"/proc/sys/net/ipv4/conf/{name}/rp_filter").read_text()))
        except (OSError, ValueError):
            if name == "all":
                return None
    return max(values)


def _dns_leak_result(config: Config, loaded: bool | None) -> CheckResult:
    """routing.mode full: AdGuard's upstream queries must take the uplink (decision 14)."""
    upstream = config.routing.default_upstream if config.routing else "-"
    if loaded:
        found = f"AdGuard asks its upstreams through uplink {upstream}"
        return CheckResult("dns leak", Verdict.OK, found)
    if loaded is None:
        unknown = "cannot tell whether AdGuard goes through the uplink"
        return CheckResult("dns leak", Verdict.WARN, unknown, SUDO_HINT)
    return CheckResult(
        "dns leak",
        Verdict.WARN,
        "AdGuard sends its DoH queries directly: the router has no dns_uplink chain",
        "vibedpn restart",
    )


def _chain_present(table: str, chain: str) -> bool | None:
    """Whether ``chain`` exists in the nft ``table``; ``None`` when nft cannot tell."""
    nft = find_nft()
    if nft is None:
        return None
    family, name = table.split()
    try:
        probe = subprocess.run(
            [nft, "list", "chain", family, name, chain], check=False, capture_output=True, text=True
        )
    except OSError:
        return None
    if probe.returncode == 0:
        return True
    return False if "No such file or directory" in probe.stderr else None


def _table_present(table: str) -> tuple[bool | None, str]:
    """Whether an nft ``table`` is loaded; ``None`` plus the reason when nft cannot tell."""
    nft = find_nft()
    if nft is None:
        return None, "nft not found on the host (apt install nftables)"
    try:
        probe = subprocess.run(
            [nft, "-j", "list", "tables"], check=False, capture_output=True, text=True
        )
    except OSError as exc:
        return None, f"cannot run nft: {exc.strerror}"
    if probe.returncode != 0:
        return None, f"nft cannot list tables: {probe.stderr.strip() or 'not root'}"
    family, name = table.split()
    try:
        entries = json.loads(probe.stdout).get("nftables", [])
    except json.JSONDecodeError:
        return None, "nft returned no JSON"
    present = any(
        isinstance(entry, dict)
        and entry.get("table", {}).get("family") == family
        and entry.get("table", {}).get("name") == name
        for entry in entries
    )
    return present, ""


def _env_matches(env_path: Path, config: Config) -> bool:
    current = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep:
            current[key.strip()] = value.strip()
    return all(current.get(key) == value for key, value in config.env_vars().items())


def _read_ip_forward() -> bool | None:
    try:
        return parse_sysctl_flag(IP_FORWARD_SYSCTL.read_text(encoding="ascii"))
    except OSError:
        return None


def _listeners() -> tuple[list[Listener] | None, str]:
    try:
        probe = subprocess.run(SS_ARGV, check=False, capture_output=True, text=True)
    except FileNotFoundError:
        return None, "`ss` not found (install iproute2)"
    except OSError as exc:
        return None, f"`ss` failed: {exc.strerror}"
    if probe.returncode != 0:
        return None, f"`ss` exited {probe.returncode}: {probe.stderr.strip()}"
    return parse_ss(probe.stdout), ""


def render(results: list[CheckResult]) -> str:
    badge = {Verdict.OK: "[ ok ]", Verdict.WARN: "[warn]", Verdict.FAIL: "[FAIL]"}
    width = max((len(item.name) for item in results), default=0)
    lines = []
    for item in results:
        line = f"{badge[item.verdict]} {item.name.ljust(width)}  {item.detail}"
        if item.hint:
            line += f" — {item.hint}"
        lines.append(line)
    counts = {verdict: sum(1 for item in results if item.verdict is verdict) for verdict in Verdict}
    lines.append(
        f"{counts[Verdict.OK]} ok, {counts[Verdict.WARN]} warn, {counts[Verdict.FAIL]} fail"
    )
    return "\n".join(lines)


def to_json(results: list[CheckResult]) -> str:
    return json.dumps([asdict(item) for item in results], ensure_ascii=False, indent=1)


def has_failures(results: list[CheckResult]) -> bool:
    return any(item.verdict is Verdict.FAIL for item in results)


def _nat_facts(config: Config | None, *, network: bool) -> dict[str, str]:
    """The node's NAT type; asked only with --network, only on a box that runs a node."""
    if not network or config is None or not config.provider.enabled:
        return {}
    client = TequilaClient()
    try:
        return {"nat": nat_type(client)}
    except MystError as exc:
        return {"nat_error": str(exc)}
    finally:
        client.close()


def _nat_results(facts: DoctorFacts) -> list[CheckResult]:
    if facts.config is None:
        return []
    result = _nat_result(facts.config, facts)
    return [] if result is None else [result]


def _nat_result(config: Config, facts: DoctorFacts) -> CheckResult | None:
    """How consumers reach the node. It is the node's own estimate: whether the UDP range is really
    open from the internet can only be seen from outside."""
    if not config.provider.enabled or not (facts.nat or facts.nat_error):
        return None
    ports = config.provider.udp_ports
    forward = f"forward UDP {ports} on the router to this box"
    if facts.nat_error:
        return CheckResult(
            "nat",
            Verdict.WARN,
            f"the node could not tell: {facts.nat_error}",
            "vibedpn logs myst-provider",
        )
    if facts.nat in NAT_OPEN:
        return CheckResult("nat", Verdict.OK, f"{facts.nat}: consumers reach the node directly")
    if facts.nat in NAT_PUNCHABLE:
        return CheckResult(
            "nat",
            Verdict.OK,
            f"{facts.nat}: reachable through hole punching; {forward} for more sessions",
        )
    if facts.nat == NAT_SYMMETRIC:
        return CheckResult(
            "nat",
            Verdict.WARN,
            "symmetric: hole punching fails, consumers rarely reach the node",
            forward,
        )
    return CheckResult("nat", Verdict.WARN, f"unknown NAT type {facts.nat!r} from the node")


def _lan_address_set(config: Config | None) -> bool | None:
    if config is None or config.network is None or config.network.mode is not NetworkMode.GATEWAY:
        return None
    ip = find_ip()
    if ip is None:
        return None
    lan = config.network.lan_interface
    try:
        listing = subprocess.run(
            [ip, "-j", "-4", "addr", "show", "dev", lan], check=True, capture_output=True, text=True
        )
        found = parse_interface(listing.stdout, lan)
    except (OSError, subprocess.CalledProcessError, ValueError):
        return None
    return found is not None and found.address == config.network.lan_address


def _gateway_results(facts: DoctorFacts) -> list[CheckResult]:
    """gateway mode: the box owns its LAN address; the OS configures it, not core."""
    config = facts.config
    if config is None or config.network is None or config.network.mode is not NetworkMode.GATEWAY:
        return []
    network = config.network
    if facts.lan_address_set is None:
        return [
            CheckResult(
                "lan address",
                Verdict.WARN,
                f"cannot read the addresses of {network.lan_interface}",
                SUDO_HINT,
            )
        ]
    if not facts.lan_address_set:
        return [
            CheckResult(
                "lan address",
                Verdict.FAIL,
                f"{network.lan_address} is not configured on {network.lan_interface}",
                "give the LAN interface a static address (docs/manuals/installation.md, gateway)",
            )
        ]
    return [
        CheckResult("lan address", Verdict.OK, f"{network.lan_address} on {network.lan_interface}")
    ]


def _lan_wireless(config: Config | None) -> bool | None:
    network = config.network if config is not None else None
    if network is None or network.wifi is None:
        return None
    return is_wireless(network.lan_interface)


def _wifi_results(facts: DoctorFacts) -> list[CheckResult]:
    """network.wifi: hostapd needs the radio itself as the LAN interface."""
    config = facts.config
    network = config.network if config is not None else None
    if network is None or network.wifi is None:
        return []
    if not facts.lan_wireless:
        return [
            CheckResult(
                "wifi",
                Verdict.FAIL,
                f"{network.lan_interface} is not a wireless interface",
                "network.wifi needs the radio as network.lan_interface",
            )
        ]
    found = f"access point {network.wifi.ssid!r} on {network.lan_interface}"
    return [CheckResult("wifi", Verdict.OK, found)]
