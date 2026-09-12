"""Host and box diagnostics for ``vibedpn doctor``: gather facts, evaluate, report — never fix.

``gather`` is the only function with side effects; ``evaluate`` and the parsers are pure and
unit-tested on fixtures. Every check yields a verdict with a detail and, when something is
wrong, a hint naming the command to run.
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
    HTPASSWD_FILE,
    SECRETS_DIR,
    WG_CLIENT_CONF,
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
from vibedpn.config import Config, Role
from vibedpn.detect import WIREGUARD_MODULE, module_present

NFTABLES_MODULE = "nf_tables"
IP_FORWARD_SYSCTL = Path("/proc/sys/net/ipv4/ip_forward")
API_HOST = "127.0.0.1"
ANY_ADDRESSES = frozenset({"0.0.0.0", "*", "::", "[::]"})
WILDCARD = "*"


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
class Listener:
    proto: str
    address: str
    port: int
    process: str  # empty when ``ss`` could not tell (not root)


@dataclass(frozen=True)
class PortNeed:
    """A port a service of this box must be able to bind."""

    service: str
    proto: str
    address: str  # a concrete address or WILDCARD
    port: int


@dataclass(frozen=True)
class DoctorFacts:
    config: Config | None
    config_error: str
    env_current: bool | None  # None: no .env yet
    secrets: dict[str, bool]
    wireguard: bool
    nf_tables: bool
    ip_forward: bool | None  # None: unreadable
    listeners: list[Listener]
    is_root: bool
    docker_error: str
    services: list[ServiceStatus] = field(default_factory=list)
    active_services: list[str] = field(default_factory=list)


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
                PortNeed("adguard", "udp", lan, 53),
                PortNeed("adguard", "tcp", lan, 53),
                PortNeed("adguard", "tcp", lan, config.dns.web_port),
            ]
        if config.ui.enabled:
            needs.append(PortNeed("ui", "tcp", lan, config.ui.port))
    if config.wg_server is not None:
        needs.append(PortNeed("wg-server", "udp", WILDCARD, config.wg_server.listen_port))
    return needs


def holder_of(need: PortNeed, listeners: list[Listener]) -> Listener | None:
    """The listener that would collide with ``need``, if any."""
    for listener in listeners:
        if listener.proto != need.proto or listener.port != need.port:
            continue
        overlap = (
            need.address == WILDCARD
            or listener.address in ANY_ADDRESSES
            or listener.address == need.address
        )
        if overlap:
            return listener
    return None


def tunnels_configured(config: Config) -> bool:
    return (
        config.wg_server is not None or config.upstreams.vps.enabled or config.upstreams.dpn.enabled
    )


def evaluate(facts: DoctorFacts) -> list[CheckResult]:  # noqa: PLR0912 - one flat table of checks
    results: list[CheckResult] = []
    config = facts.config
    if config is None:
        results.append(CheckResult("config", Verdict.FAIL, facts.config_error, "vibedpn init"))
    else:
        profiles = ",".join(profile.value for profile in config.compose_profiles())
        results.append(
            CheckResult("config", Verdict.OK, f"role {config.role.value}, profiles {profiles}")
        )
        if facts.env_current is None:
            results.append(CheckResult("env", Verdict.WARN, ".env not written yet", "vibedpn up"))
        elif not facts.env_current:
            results.append(
                CheckResult("env", Verdict.WARN, ".env is behind config.yaml", "vibedpn up")
            )
        else:
            results.append(CheckResult("env", Verdict.OK, ".env matches config.yaml"))
        results.extend(_secrets_results(config, facts.secrets))

    if facts.wireguard:
        results.append(CheckResult("wireguard", Verdict.OK, "kernel module available"))
    elif config is not None and tunnels_configured(config):
        results.append(
            CheckResult(
                "wireguard",
                Verdict.FAIL,
                "kernel module missing; tunnels cannot start",
                "use a stock Debian 12/13 or Raspberry Pi OS kernel (wireguard is built in)",
            )
        )
    else:
        results.append(
            CheckResult(
                "wireguard", Verdict.WARN, "kernel module missing (no tunnel configured yet)"
            )
        )
    if facts.nf_tables:
        results.append(CheckResult("nf_tables", Verdict.OK, "kernel module available"))
    else:
        results.append(
            CheckResult(
                "nf_tables",
                Verdict.FAIL,
                "kernel module missing; the router engine and Docker need it",
            )
        )
    if facts.ip_forward is None:
        results.append(CheckResult("ip_forward", Verdict.WARN, f"cannot read {IP_FORWARD_SYSCTL}"))
    elif facts.ip_forward:
        results.append(CheckResult("ip_forward", Verdict.OK, "net.ipv4.ip_forward=1"))
    else:
        results.append(
            CheckResult(
                "ip_forward",
                Verdict.FAIL,
                "net.ipv4.ip_forward=0; Docker normally enables it at start",
                "sysctl -w net.ipv4.ip_forward=1 and persist it in /etc/sysctl.d/",
            )
        )

    if facts.docker_error:
        results.append(CheckResult("docker", Verdict.FAIL, facts.docker_error))
    else:
        results.append(CheckResult("docker", Verdict.OK, "daemon reachable"))
    if config is not None:
        results.extend(_port_results(config, facts))
        if not facts.docker_error:
            results.extend(_service_results(facts))
    return results


def _secrets_results(config: Config, secrets: dict[str, bool]) -> list[CheckResult]:
    needed = []
    if config.role is not Role.VPS:
        needed.append(HTPASSWD_FILE)
    if config.role is Role.CLIENT:
        needed.append(WG_CLIENT_CONF)
    missing = [name for name in needed if not secrets.get(name)]
    if missing:
        return [
            CheckResult(
                "secrets", Verdict.FAIL, f"missing {', '.join(missing)}", "vibedpn init --force"
            )
        ]
    return [
        CheckResult(
            "secrets", Verdict.OK, ", ".join(needed) if needed else "none needed for this role"
        )
    ]


def _port_results(config: Config, facts: DoctorFacts) -> list[CheckResult]:
    running = {item.service for item in facts.services if item.state == "running"}
    results = []
    for need in port_needs(config):
        label = f"{need.proto}/{need.port}"
        holder = holder_of(need, facts.listeners)
        if holder is None:
            results.append(CheckResult(f"port {label}", Verdict.OK, f"free for {need.service}"))
        elif need.service in running:
            results.append(CheckResult(f"port {label}", Verdict.OK, f"held by our {need.service}"))
        else:
            who = holder.process or (
                "unknown process" + ("" if facts.is_root else "; run with sudo to see it")
            )
            results.append(
                CheckResult(
                    f"port {label}",
                    Verdict.FAIL,
                    f"taken by {who} on {holder.address}, needed by {need.service}",
                    "stop that service or change the port in config.yaml",
                )
            )
    return results


def _service_results(facts: DoctorFacts) -> list[CheckResult]:
    by_name = {item.service: item for item in facts.services}
    unhealthy = [name for name, item in by_name.items() if item.health == "unhealthy"]
    missing = [
        name
        for name in facts.active_services
        if by_name.get(name) is None or by_name[name].state != "running"
    ]
    if unhealthy:
        return [
            CheckResult(
                "services",
                Verdict.FAIL,
                f"unhealthy: {', '.join(unhealthy)}",
                "vibedpn logs <service>",
            )
        ]
    if missing:
        return [
            CheckResult(
                "services", Verdict.WARN, f"not running: {', '.join(missing)}", "vibedpn up"
            )
        ]
    return [CheckResult("services", Verdict.OK, f"{len(facts.active_services)} running")]


def gather(box_dir: Path) -> DoctorFacts:
    """Collect every fact the checks need; failures become facts, not exceptions."""
    config: Config | None = None
    config_error = ""
    try:
        config = check_box(box_dir)
    except ComposeError as exc:
        config_error = str(exc)
    env_current: bool | None = None
    env_path = box_dir / ENV_FILE
    if config is not None and env_path.is_file():
        env_current = _env_matches(env_path, config)
    secrets = {
        name: (box_dir / SECRETS_DIR / name).is_file() for name in (HTPASSWD_FILE, WG_CLIENT_CONF)
    }
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
    return DoctorFacts(
        config=config,
        config_error=config_error,
        env_current=env_current,
        secrets=secrets,
        wireguard=module_present(WIREGUARD_MODULE),
        nf_tables=module_present(NFTABLES_MODULE),
        ip_forward=_read_ip_forward(),
        listeners=_listeners(),
        is_root=os.geteuid() == 0,
        docker_error=docker_error,
        services=services,
        active_services=active,
    )


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


def _listeners() -> list[Listener]:
    try:
        probe = subprocess.run(["ss", "-H", "-lntup"], check=False, capture_output=True, text=True)
    except FileNotFoundError:
        return []
    return parse_ss(probe.stdout)


def render(results: list[CheckResult]) -> str:
    badge = {Verdict.OK: "[ ok ]", Verdict.WARN: "[warn]", Verdict.FAIL: "[FAIL]"}
    width = max(len(item.name) for item in results)
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
