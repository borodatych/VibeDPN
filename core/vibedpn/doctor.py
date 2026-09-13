"""Host and box diagnostics for ``vibedpn doctor``: gather facts, evaluate, report — never fix.

``gather`` is the only function with side effects; ``evaluate`` and the parsers are pure and
unit-tested on fixtures. A fact that could not be collected is ``None`` (or carries an error
text) and turns into a ``warn`` that names what to run — never into a false ``ok`` or ``fail``.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path

from vibedpn.bootstrap import (
    ENV_FILE,
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
from vibedpn.config import Config, Profile, Role, parse_port_range
from vibedpn.detect import SSHD, WIREGUARD_MODULE, module_present
from vibedpn.engine.myst import NODEUI_PORT, TEQUILAPI_PORT
from vibedpn.engine.router import (
    EGRESS_TABLE,
    NFT_TABLE,
    RouterError,
    docker_user_chain,
    docker_user_rules,
    find_nft,
    plan_docker_user,
)
from vibedpn.engine.wg import SERVER_CONF_FILE, SERVER_KEY_FILE, server_address
from vibedpn.engine.wg import SERVER_DIR as WG_SERVER_DIR

NFTABLES_MODULE = "nf_tables"
IP_FORWARD_SYSCTL = Path("/proc/sys/net/ipv4/ip_forward")
SS_ARGV = ["ss", "-H", "-lntup"]
API_HOST = "127.0.0.1"
DNS_PORT = 53
CORE_PROCESS_NAMES = frozenset({"vibedpn-core"})  # comm of the console script in `ss -p`
ANY_ADDRESSES = frozenset({"0.0.0.0", "*", "::", "[::]"})
WILDCARD = "*"
RUNNING_STATE = "running"
NEVER_STARTED_STATE = "created"
SUDO_HINT = "sudo vibedpn doctor"


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
            "add the port to firewall.ssh_ports in config.yaml, then vibedpn restart",
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


def gather(box_dir: Path) -> DoctorFacts:
    """Collect every fact the checks need; failures become facts, not exceptions."""
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
            docker_user, docker_user_error = _docker_user_current(config)
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


def _docker_user_current(config: Config) -> tuple[bool | None, str]:
    """Whether ``DOCKER-USER`` already holds exactly our rules (or does not exist at all)."""
    if os.geteuid() != 0:
        return None, "cannot read DOCKER-USER without root"
    try:
        found = docker_user_chain()
    except RouterError as exc:
        return None, str(exc)
    if found is None:
        return True, ""
    delete, insert = plan_docker_user(found[1], docker_user_rules(config))
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
