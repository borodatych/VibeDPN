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
    public_address,
    write_box,
)
from vibedpn.config import Role
from vibedpn.detect import DetectError, HostProbe

MIN_PASSWORD_LENGTH = 8
EXIT_USER_ERROR = 1

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


def _ask_role() -> Role:
    choice = typer.prompt("Role", type=click.Choice([role.value for role in Role]))
    return Role(choice)


def _ask_password() -> str:
    password: str = typer.prompt("UI password", hide_input=True, confirmation_prompt=True)
    if len(password) < MIN_PASSWORD_LENGTH:
        raise _fail(f"the password must be at least {MIN_PASSWORD_LENGTH} characters long")
    return password


def _read_password_file(path: Path) -> str:
    try:
        password = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise _fail(f"cannot read {path}: {exc.strerror}") from None
    if len(password) < MIN_PASSWORD_LENGTH:
        raise _fail(f"the password must be at least {MIN_PASSWORD_LENGTH} characters long")
    return password


def _collect_answers(
    role: Role | None,
    peer_config: Path | None,
    endpoint: str | None,
    password_file: Path | None,
    facts: HostFacts,
) -> Answers:
    """Ask only what cannot be detected or was not passed as a flag."""
    role = role or _ask_role()
    password = None
    if role is not Role.VPS:
        password = _read_password_file(password_file) if password_file else _ask_password()
    if role is Role.CLIENT and peer_config is None:
        peer_config = Path(typer.prompt("Path to the WireGuard peer file (.conf) from the VPS"))
        if not peer_config.is_file():
            raise _fail(f"{peer_config} is not a file")
    if role is Role.VPS and endpoint is None and public_address(facts) is None:
        endpoint = typer.prompt("Public host or IPv4 of this VPS")
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
    box_dir: Annotated[
        Path,
        typer.Option("--dir", envvar="VIBEDPN_DIR", help="Installation directory."),
    ] = DEFAULT_BOX_DIR,
    force: Annotated[
        bool,
        typer.Option("--force", help="Replace an existing config.yaml (kept as config.yaml.bak)."),
    ] = False,
) -> None:
    """Configure this box: detect the network, ask what cannot be detected, write config.yaml,
    .env and secrets/."""
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
    for path in written:
        typer.echo(f"wrote {path}")
    if not facts.wireguard_module:
        typer.secho(
            "warning: the wireguard kernel module is not available; tunnels will not start",
            fg=typer.colors.YELLOW,
            err=True,
        )
    typer.echo(f"Role {answers.role.value} configured. Next step: vibedpn up")
