"""``vibedpn`` command line: a thin client over ``core`` and Docker Compose.

Stage 1 ships ``init``; ``up``, ``down``, ``restart``, ``status``, ``logs`` and ``doctor`` follow.
"""

import time
from collections.abc import Callable
from dataclasses import replace
from enum import StrEnum
from pathlib import Path
from typing import Annotated, TypeVar

import click
import typer

from vibedpn import __version__
from vibedpn.api import client as core_api
from vibedpn.api.client import (
    CoreUnreachableError,
    DeviceRequestError,
    PeerRequestError,
    StatsUnavailableError,
    fetch_provider_stats,
)
from vibedpn.api.models import PeerFile
from vibedpn.atomic import write_private
from vibedpn.bootstrap import (
    CONFIG_FILE,
    DEFAULT_BOX_DIR,
    Answers,
    BootstrapError,
    HostFacts,
    build_config,
    check_password,
    ensure_replaceable,
    public_address,
    write_box,
)
from vibedpn.compose import (
    DEFAULT_LOG_TAIL,
    ComposeError,
    capture,
    check_box,
    check_secrets,
    compose_argv,
    parse_ps,
    preflight,
    refresh_env,
    run,
    stale_services,
)
from vibedpn.config import (
    Config,
    DevicePolicy,
    Role,
    RoutingMode,
    UiVariant,
    Upstream,
    check_endpoint,
)
from vibedpn.config_edit import ConfigEditError, set_routing
from vibedpn.detect import DetectError, HostProbe
from vibedpn.device_view import render_devices
from vibedpn.doctor import evaluate, gather, has_failures, render, to_json
from vibedpn.engine.myst import render_stats
from vibedpn.tunnel_view import qr_code, render_peers

EXIT_USER_ERROR = 1
T = TypeVar("T")
PANEL_PASSWORD_PROMPT = "Password for the panels (VibeDPN UI and the node's NodeUI)"

BoxDir = Annotated[
    Path, typer.Option("--dir", envvar="VIBEDPN_DIR", help="Installation directory.")
]

app = typer.Typer(
    name="vibedpn",
    help="VibeDPN: one box, one command. Provider node, private tunnel, LAN router.",
    add_completion=False,
    no_args_is_help=True,
)


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"vibedpn {__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            help="Show the version and exit.",
            callback=_print_version,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """VibeDPN: one box, one command. Provider node, private tunnel, LAN router."""


def _fail(message: str) -> typer.Exit:
    typer.secho(f"error: {message}", fg=typer.colors.RED, err=True)
    return typer.Exit(EXIT_USER_ERROR)


def _retry(message: str) -> None:
    typer.secho(f"{message}; try again", fg=typer.colors.YELLOW, err=True)


def _ask_role() -> Role:
    choice = typer.prompt("Role", type=click.Choice([role.value for role in Role]))
    return Role(choice)


def _ask_password() -> str:
    while True:
        password: str = typer.prompt(
            PANEL_PASSWORD_PROMPT, hide_input=True, confirmation_prompt=True
        )
        try:
            check_password(password)
        except BootstrapError as exc:
            _retry(str(exc))
            continue
        return password


def _read_password_file(path: Path) -> str:
    try:
        password = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise _fail(f"cannot read {path}: {exc.strerror}") from None
    try:
        check_password(password)
    except BootstrapError as exc:
        raise _fail(str(exc)) from None
    return password


def _ask_peer_config() -> Path:
    while True:
        answer = typer.prompt("Path to the WireGuard peer file (.conf) from the VPS")
        path = Path(answer).expanduser()
        if path.is_file():
            return path
        _retry(f"{path} is not a file")


def _ask_endpoint() -> str:
    while True:
        answer: str = typer.prompt("Public host or IPv4 of this VPS")
        try:
            return check_endpoint(answer.strip())
        except ValueError as exc:
            _retry(f"{exc}; give the host without a port")


def _check_flags_for_role(
    role: Role, peer_config: Path | None, endpoint: str | None, password_file: Path | None
) -> None:
    """A flag of another role is a mistake, not something to ignore silently."""
    if peer_config is not None and role is not Role.CLIENT:
        raise _fail("--peer-config is only used with --role client")
    if endpoint is not None and role is not Role.VPS:
        raise _fail("--endpoint is only used with --role vps")
    if endpoint is not None:
        try:
            check_endpoint(endpoint)
        except ValueError as exc:
            raise _fail(f"--endpoint: {exc}; give the host without a port") from None


def _collect_answers(
    role: Role | None,
    peer_config: Path | None,
    endpoint: str | None,
    password_file: Path | None,
    facts: HostFacts,
) -> Answers:
    """Ask only what cannot be detected or was not passed as a flag; fail early on known facts."""
    role = role or _ask_role()
    _check_flags_for_role(role, peer_config, endpoint, password_file)
    if role is not Role.VPS and facts.interface is None:
        raise _fail("no interface with a default route was found; connect the box to the LAN first")
    password = _read_password_file(password_file) if password_file else _ask_password()
    if role is Role.CLIENT and peer_config is None:
        peer_config = _ask_peer_config()
    if role is Role.VPS and endpoint is None and public_address(facts) is None:
        endpoint = _ask_endpoint()
    return Answers(role=role, password=password, peer_config=peer_config, endpoint=endpoint)


@app.command()
def init(
    role: Annotated[Role | None, typer.Option(help="Box role: home, vps or client.")] = None,
    peer_config: Annotated[
        Path | None,
        typer.Option(
            help="WireGuard peer file from `vibedpn peer export` on the VPS (role client).",
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ] = None,
    endpoint: Annotated[
        str | None,
        typer.Option(help="Public host or IPv4 of this VPS (role vps); detected when possible."),
    ] = None,
    ui_variant: Annotated[
        UiVariant | None,
        typer.Option(help="Panel variant: full, or lite for a Raspberry Pi; else by host memory."),
    ] = None,
    password_file: Annotated[
        Path | None,
        typer.Option(
            help="File with the panel password (VibeDPN UI, NodeUI); else asked interactively.",
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ] = None,
    box_dir: BoxDir = DEFAULT_BOX_DIR,
    force: Annotated[
        bool,
        typer.Option("--force", help="Replace an existing config.yaml (kept as config.yaml.bak)."),
    ] = False,
) -> None:
    """Configure this box: detect the network, ask what cannot be detected, write config.yaml,
    .env and secrets/."""
    try:
        ensure_replaceable(box_dir, force=force)
    except BootstrapError as exc:
        raise _fail(str(exc)) from None
    probe = HostProbe()
    try:
        facts = HostFacts(
            interface=probe.default_interface(),
            wireguard_module=probe.wireguard_module_present(),
            ssh_ports=probe.ssh_ports(),
            memory_bytes=probe.memory_bytes(),
        )
    except DetectError as exc:
        raise _fail(str(exc)) from None
    if facts.interface is not None:
        detected = facts.interface
        typer.echo(f"Detected {detected.name}: {detected.address}/{detected.prefixlen}")
    answers = replace(
        _collect_answers(role, peer_config, endpoint, password_file, facts), ui_variant=ui_variant
    )
    try:
        config = build_config(answers, facts)
        written = write_box(box_dir, config, answers, force=force)
    except BootstrapError as exc:
        raise _fail(str(exc)) from None
    for path in written.files:
        typer.echo(f"wrote {path}")
    for path in written.retired:
        typer.echo(f"set aside a secret of the previous role: {path}")
    if facts.wireguard_module is False:
        typer.secho(
            "warning: the wireguard kernel module is not available; tunnels will not start",
            fg=typer.colors.YELLOW,
            err=True,
        )
    elif facts.wireguard_module is None:
        typer.secho(
            "warning: could not check the wireguard kernel module (modprobe not found)",
            fg=typer.colors.YELLOW,
            err=True,
        )
    if config.network is not None and config.ui.enabled:
        typer.echo(f"Panel variant {config.ui.variant.value} (ui.variant in config.yaml)")
    typer.echo(f"Role {answers.role.value} configured. Next step: vibedpn up")


def _prepare(box_dir: Path, *, refresh: bool) -> Config:
    """Common start of every Compose command: a valid box, a usable Docker, a fresh ``.env``."""
    try:
        config = check_box(box_dir)
        preflight()
        if refresh:
            check_secrets(box_dir, config)
            refresh_env(box_dir, config)
    except ComposeError as exc:
        raise _fail(str(exc)) from None
    return config


def _compose(box_dir: Path, *args: str, all_profiles: bool = False) -> None:
    """Run Compose live and exit with its code when it fails."""
    try:
        code = run(compose_argv(box_dir, *args, all_profiles=all_profiles))
    except ComposeError as exc:
        raise _fail(str(exc)) from None
    if code != 0:
        raise typer.Exit(code)


def _retire_stale(box_dir: Path) -> None:
    """Stop and remove containers of profiles the (fresh) .env no longer activates."""
    try:
        stale = stale_services(
            capture(compose_argv(box_dir, "config", "--services", all_profiles=True)),
            capture(compose_argv(box_dir, "config", "--services")),
        )
    except ComposeError as exc:
        raise _fail(str(exc)) from None
    if stale:
        _compose(box_dir, "rm", "--stop", "--force", *stale, all_profiles=True)


@app.command()
def up(box_dir: BoxDir = DEFAULT_BOX_DIR) -> None:
    """Start the box: derive .env from config.yaml and bring the role's services up."""
    _prepare(box_dir, refresh=True)
    _retire_stale(box_dir)
    _compose(box_dir, "up", "-d", "--remove-orphans")


@app.command()
def down(box_dir: BoxDir = DEFAULT_BOX_DIR) -> None:
    """Stop and remove every service of the box, whatever profile it belongs to."""
    _prepare(box_dir, refresh=False)
    _compose(box_dir, "down", all_profiles=True)


@app.command()
def restart(box_dir: BoxDir = DEFAULT_BOX_DIR) -> None:
    """Apply config.yaml changes: refresh .env, stop the box, bring it up again.

    Not `compose restart`: it restarts every container at once and ignores
    `depends_on: condition: service_healthy`, so wg-server would read the wg0.conf that core has
    not re-rendered yet. `up` honours the conditions, and recreates what changed on the way.
    """
    _prepare(box_dir, refresh=True)
    _retire_stale(box_dir)
    _compose(box_dir, "stop")
    _compose(box_dir, "up", "-d", "--remove-orphans")


def _routing_line(config: Config) -> str:
    if config.routing is None:
        return "routing: -"
    return (
        f"routing: mode={config.routing.mode.value}"
        f" default_upstream={config.routing.default_upstream.value}"
        f" failopen={str(config.routing.failopen).lower()}"
    )


class SwitchableMode(StrEnum):
    """Modes the router implements; ``smart`` joins in Stage 10."""

    OFF = RoutingMode.OFF.value
    FULL = RoutingMode.FULL.value


CORE_SERVICE = "core"
ADGUARD_SERVICE = "adguard"
RUNNING_STATE = "running"


def _switch_routing(
    box_dir: Path, *, mode: RoutingMode | None = None, upstream: Upstream | None = None
) -> None:
    """Change routing in config.yaml and, when core runs, restart only core (and adguard, which
    reads aaaa_disabled at start): the router is applied at core's start, and the tunnel and the
    other containers keep running."""
    _prepare(box_dir, refresh=False)
    try:
        config, changed = set_routing(box_dir / CONFIG_FILE, mode=mode, upstream=upstream)
    except ConfigEditError as exc:
        raise _fail(str(exc)) from None
    if not changed:
        typer.echo(f"{_routing_line(config)} (already set)")
        return
    try:
        services = parse_ps(capture(compose_argv(box_dir, "ps", "-a", "--format", "json")))
    except ComposeError as exc:
        raise _fail(str(exc)) from None
    running = {item.service for item in services if item.state == RUNNING_STATE}
    if CORE_SERVICE in running:
        _compose(box_dir, "restart", "--no-deps", CORE_SERVICE)
        names = [CORE_SERVICE]
        if ADGUARD_SERVICE in running:
            # AdGuard reads its file only at start, and core rewrites aaaa_disabled at its own
            # start. Restarted together, AdGuard won the race and kept the old mode (smoke): it
            # restarts only once core is healthy again.
            _compose(box_dir, "up", "-d", "--no-deps", "--wait", CORE_SERVICE)
            _compose(box_dir, "restart", "--no-deps", ADGUARD_SERVICE)
            names.append(ADGUARD_SERVICE)
        typer.echo(f"{_routing_line(config)} (applied: {', '.join(names)} restarted)")
    else:
        typer.echo(f"{_routing_line(config)} (saved; applies at `vibedpn up`)")


@app.command()
def mode(
    value: Annotated[SwitchableMode, typer.Argument(help="off: LAN direct; full: all via uplink.")],
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """Switch routing.mode of the LAN router and apply it."""
    _switch_routing(box_dir, mode=RoutingMode(value.value))


@app.command()
def upstream(
    value: Annotated[Upstream, typer.Argument(help="The uplink of routing.mode full.")],
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """Switch routing.default_upstream and apply it."""
    _switch_routing(box_dir, upstream=value)


@app.command()
def status(box_dir: BoxDir = DEFAULT_BOX_DIR) -> None:
    """Role and routing from config.yaml, then the state of every container."""
    config = _prepare(box_dir, refresh=False)
    typer.echo(f"role: {config.role.value}")
    if config.routing is not None:
        typer.echo(_routing_line(config))
    uplinks = [name for name in ("vps", "dpn") if config.upstreams.is_enabled(Upstream(name))]
    typer.echo(f"uplinks: {', '.join(uplinks) or '-'}")
    typer.echo(f"profiles: {','.join(profile.value for profile in config.compose_profiles())}")
    try:
        services = parse_ps(capture(compose_argv(box_dir, "ps", "-a", "--format", "json")))
    except ComposeError as exc:
        raise _fail(str(exc)) from None
    if not services:
        typer.echo("containers: none (run `vibedpn up`)")
        return
    width = max(len(item.service) for item in services)
    for item in services:
        typer.echo(f"{item.service.ljust(width)}  {item.state:<8} {item.health:<9} {item.status}")
    for line in _node_lines(config):
        typer.echo(line)


def _node_lines(config: Config) -> list[str]:
    """The node block: statistics through ``core``, or one line saying why there are none."""
    if not config.provider.enabled:
        return []
    try:
        stats = fetch_provider_stats(config.api.port)
    except CoreUnreachableError:
        return ["node: core is not running (run `vibedpn up`, then `vibedpn doctor`)"]
    except StatsUnavailableError as exc:
        return [f"node: unavailable ({exc})"]
    return render_stats(stats)


@app.command()
def logs(
    service: Annotated[str | None, typer.Argument(help="One service, or all when omitted.")] = None,
    follow: Annotated[bool, typer.Option("--follow", "-f", help="Keep streaming.")] = False,
    tail: Annotated[int, typer.Option("--tail", help="Lines per container.")] = DEFAULT_LOG_TAIL,
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """Container logs (docker compose logs)."""
    _prepare(box_dir, refresh=False)
    args = ["logs", "--tail", str(tail)]
    if follow:
        args.append("--follow")
    if service:
        args.append(service)
    _compose(box_dir, *args, all_profiles=True)


@app.command()
def doctor(
    box_dir: BoxDir = DEFAULT_BOX_DIR,
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
    network: Annotated[
        bool,
        typer.Option(
            "--network",
            help="Also ask api.ipify.org for the exit address of the host and of every uplink.",
        ),
    ] = False,
) -> None:
    """Check the host and the box: kernel modules, forwarding, ports, Docker, services.

    Reports and hints only; nothing is changed. Exit code 1 when any check fails. Without
    --network nothing leaves the box.
    """
    results = evaluate(gather(box_dir, network=network))
    typer.echo(to_json(results) if as_json else render(results))
    if has_failures(results):
        raise typer.Exit(EXIT_USER_ERROR)


peer_app = typer.Typer(
    help="Tunnel peers of this VPS: the home boxes that connect to it.",
    no_args_is_help=True,
)
app.add_typer(peer_app, name="peer")
device_app = typer.Typer(
    help="LAN devices the box has seen and their policies.",
    no_args_is_help=True,
)
app.add_typer(device_app, name="device")

PeerName = Annotated[
    str, typer.Argument(help="Peer name: 1-32 lowercase letters, digits and hyphens.")
]
OutFile = Annotated[
    Path | None,
    typer.Option(
        "--out", dir_okay=False, help="Write the peer file here (mode 600) instead of printing it."
    ),
]
Force = Annotated[bool, typer.Option("--force", help="Overwrite the --out file if it exists.")]


def _vps_box(box_dir: Path) -> Config:
    try:
        config = check_box(box_dir)
    except ComposeError as exc:
        raise _fail(str(exc)) from None
    if config.wg_server is None:
        raise _fail(f"tunnel peers live on the VPS; this box has role {config.role.value}")
    return config


def _core_call(call: Callable[[], T]) -> T:
    """Peers and devices are kept by core: translate its failures into one line."""
    try:
        return call()
    except CoreUnreachableError:
        raise _fail("core is not running; start the box with `vibedpn up`") from None
    except (PeerRequestError, DeviceRequestError) as exc:
        raise _fail(str(exc)) from None


def _deliver(peer: PeerFile, out: Path | None, *, force: bool) -> None:
    """Print the file with its QR code, or write it for `init --peer-config`."""
    if out is None:
        typer.echo(peer.config, nl=False)
        typer.echo(qr_code(peer.config), nl=False)
        typer.echo("Save the text above as FILE on the home box (mode 600), then run:")
        target = "FILE"
    else:
        # The file holds the box's private key: never write it through a link that points
        # somewhere else, and never into an existing file whose mode would apply to it first.
        if out.is_symlink():
            raise _fail(f"{out} is a symlink; write the peer file to a plain path")
        if out.exists() and not force:
            raise _fail(f"{out} already exists; pass --force to overwrite it")
        try:
            write_private(out, peer.config)
        except OSError as exc:
            raise _fail(f"cannot write {out}: {exc.strerror}") from None
        typer.echo(
            f"wrote {out} (peer {peer.name}, {peer.address}); copy it to the home box, then:"
        )
        target = str(out)
    typer.echo(f"  sudo vibedpn init --role client --peer-config {target}")


@peer_app.command("add")
def peer_add(
    name: PeerName,
    out: OutFile = None,
    force: Force = False,
    tunnel_only: Annotated[
        bool,
        typer.Option(
            "--tunnel-only",
            help="Route only the tunnel subnet through this peer: a laptop or phone that needs"
            " the node panel, not a home box that sends all its traffic through the VPS.",
        ),
    ] = False,
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """Register a home box: a key pair and a tunnel address, applied to the running server."""
    config = _vps_box(box_dir)
    peer = _core_call(lambda: core_api.add_peer(config.api.port, name, tunnel_only=tunnel_only))
    _deliver(peer, out, force=force)


@peer_app.command("export")
def peer_export(
    name: PeerName,
    out: OutFile = None,
    force: Force = False,
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """Print a peer's WireGuard file again with its QR code, or write it with --out."""
    config = _vps_box(box_dir)
    peer = _core_call(lambda: core_api.export_peer(config.api.port, name))
    _deliver(peer, out, force=force)


@peer_app.command("list")
def peer_list(box_dir: BoxDir = DEFAULT_BOX_DIR) -> None:
    """Every peer with its address and the live state of its tunnel."""
    config = _vps_box(box_dir)
    peers = _core_call(lambda: core_api.list_peers(config.api.port))
    for line in render_peers(peers, time.time()):
        typer.echo(line)


@peer_app.command("rm")
def peer_rm(
    name: PeerName,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation.")] = False,
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """Remove a peer: its home box loses the tunnel at once."""
    config = _vps_box(box_dir)
    if not yes and not typer.confirm(f"Remove peer {name}? Its home box loses the tunnel"):
        raise typer.Exit(EXIT_USER_ERROR)
    _core_call(lambda: core_api.remove_peer(config.api.port, name))
    typer.echo(f"removed peer {name}")


def _lan_box(box_dir: Path) -> Config:
    try:
        config = check_box(box_dir)
    except ComposeError as exc:
        raise _fail(str(exc)) from None
    if config.network is None:
        raise _fail(f"LAN devices live on a box with a LAN; this box has role {config.role.value}")
    return config


DeviceId = Annotated[str, typer.Argument(help="The device: its MAC, or its IPv4 address.")]


@device_app.command("list")
def device_list(box_dir: BoxDir = DEFAULT_BOX_DIR) -> None:
    """Every LAN device that has used the box, with its name, address, MAC and policy."""
    config = _lan_box(box_dir)
    devices = _core_call(lambda: core_api.list_devices(config.api.port))
    for line in render_devices(devices, time.time()):
        typer.echo(line)


@device_app.command("set")
def device_set(
    ident: DeviceId,
    policy: Annotated[DevicePolicy, typer.Argument(help="vps | dpn | bypass | block.")],
    name: Annotated[str | None, typer.Option("--name", help="A name for config.yaml.")] = None,
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """Give a device its own policy; core writes config.yaml and applies it without a restart."""
    config = _lan_box(box_dir)
    view = _core_call(lambda: core_api.set_device(config.api.port, ident, policy, name))
    typer.echo(f"{view.name} ({view.mac or view.ip}): policy {view.policy}, applied")


@device_app.command("unset")
def device_unset(ident: DeviceId, box_dir: BoxDir = DEFAULT_BOX_DIR) -> None:
    """Remove a device's own policy: it follows routing.mode again."""
    config = _lan_box(box_dir)
    _core_call(lambda: core_api.unset_device(config.api.port, ident))
    typer.echo(f"{ident}: own policy removed, follows routing.mode")
