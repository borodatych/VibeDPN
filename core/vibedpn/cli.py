"""``vibedpn`` command line: a thin client over ``core`` and Docker Compose.

Stage 1 ships ``init``; ``up``, ``down``, ``restart``, ``status``, ``logs`` and ``doctor`` follow.
"""

from pathlib import Path
from typing import Annotated

import click
import typer

from vibedpn import __version__
from vibedpn.bootstrap import (
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
    compose_argv,
    parse_ps,
    preflight,
    refresh_env,
    run,
    stale_services,
)
from vibedpn.config import Config, Role, Upstream, check_endpoint
from vibedpn.detect import DetectError, HostProbe
from vibedpn.doctor import evaluate, gather, has_failures, render, to_json

EXIT_USER_ERROR = 1

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
        password: str = typer.prompt("UI password", hide_input=True, confirmation_prompt=True)
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
    if password_file is not None and role is Role.VPS:
        raise _fail("--password-file is not used with --role vps: a VPS has no UI")
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
    password = None
    if role is not Role.VPS:
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
    password_file: Annotated[
        Path | None,
        typer.Option(
            help="File with the UI password (roles home, client); asked interactively otherwise.",
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
        )
    except DetectError as exc:
        raise _fail(str(exc)) from None
    if facts.interface is not None:
        detected = facts.interface
        typer.echo(f"Detected {detected.name}: {detected.address}/{detected.prefixlen}")
    answers = _collect_answers(role, peer_config, endpoint, password_file, facts)
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
    typer.echo(f"Role {answers.role.value} configured. Next step: vibedpn up")


def _prepare(box_dir: Path, *, refresh: bool) -> Config:
    """Common start of every Compose command: a valid box, a usable Docker, a fresh ``.env``."""
    try:
        config = check_box(box_dir)
        preflight()
        if refresh:
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
    """Apply config.yaml changes: refresh .env, recreate what changed, restart the rest."""
    _prepare(box_dir, refresh=True)
    _retire_stale(box_dir)
    _compose(box_dir, "up", "-d", "--remove-orphans")
    _compose(box_dir, "restart")


@app.command()
def status(box_dir: BoxDir = DEFAULT_BOX_DIR) -> None:
    """Role and routing from config.yaml, then the state of every container."""
    config = _prepare(box_dir, refresh=False)
    typer.echo(f"role: {config.role.value}")
    if config.routing is not None:
        typer.echo(
            f"routing: mode={config.routing.mode.value}"
            f" default_upstream={config.routing.default_upstream.value}"
            f" failopen={str(config.routing.failopen).lower()}"
        )
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
) -> None:
    """Check the host and the box: kernel modules, forwarding, ports, Docker, services.

    Reports and hints only; nothing is changed. Exit code 1 when any check fails.
    """
    results = evaluate(gather(box_dir))
    typer.echo(to_json(results) if as_json else render(results))
    if has_failures(results):
        raise typer.Exit(EXIT_USER_ERROR)
