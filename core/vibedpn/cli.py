"""``vibedpn`` command line: a thin client over ``core`` and Docker Compose.

Stage 1 ships ``init``; ``up``, ``down``, ``restart``, ``status``, ``logs`` and ``doctor`` follow.
"""

import os
import sys
import time
from collections.abc import Callable
from dataclasses import replace
from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import Annotated, TypeVar

import click
import typer
from pydantic import ValidationError

from vibedpn import __version__
from vibedpn.api import client as core_api
from vibedpn.api.client import (
    CoreUnreachableError,
    DeviceRequestError,
    PeerRequestError,
    StatsUnavailableError,
    fetch_provider_stats,
)
from vibedpn.api.models import (
    AccessLink,
    DomainListUpdate,
    DomainListView,
    DomainRuleUpdate,
    JournalEntryView,
    NetworkRuleUpdate,
    PeerFile,
)
from vibedpn.atomic import write_private
from vibedpn.bootstrap import (
    CONFIG_FILE,
    DEFAULT_BOX_DIR,
    ENV_FILE,
    SECRET_DIR_MODE,
    SECRETS_DIR,
    XRAY_LINK_FILE,
    Answers,
    BootstrapError,
    HostFacts,
    build_config,
    check_password,
    ensure_country_secrets,
    ensure_replaceable,
    public_address,
    read_env,
    read_peer_config,
    set_panel_password,
    wg_uplink_file,
    write_box,
)
from vibedpn.compose import (
    DEFAULT_LOG_TAIL,
    IMAGE_LISTING,
    ComposeError,
    capture,
    check_box,
    check_secrets,
    compose_argv,
    kept_services,
    parse_ps,
    preflight,
    refresh_countries,
    refresh_env,
    refresh_tor_bridges,
    refresh_wg_uplinks,
    refresh_xray_config,
    run,
    stale_services,
)
from vibedpn.config import (
    WG_UPLINK_NAME,
    Config,
    DevicePolicy,
    DomainVia,
    NetworkMode,
    Role,
    RoutingMode,
    UiVariant,
    Upstream,
    WifiConfig,
    check_endpoint,
    recreated_services,
)
from vibedpn.config_edit import (
    ConfigEditError,
    WgUplinkNotFoundError,
    remove_wg_uplink,
    set_access,
    set_ddns,
    set_routing,
    set_tor_uplink,
    set_wg_uplink,
    set_xray_uplink,
)
from vibedpn.detect import DetectError, HostProbe, find_tool
from vibedpn.device_view import render_devices
from vibedpn.doctor import evaluate, gather, has_failures, render, to_json
from vibedpn.engine.apply import (
    APPLY_UNIT,
    BOX_DATA_DIR,
    ApplyResult,
    read_request,
    read_result,
    render_units,
    write_result,
)
from vibedpn.engine.backup import (
    BACKUPS_DIR,
    BackupError,
    create_archive,
    read_members,
    restore_archive,
    stamp,
)
from vibedpn.engine.consumer import (
    CONSUMER_TEQUILAPI,
    CONSUMER_TIMEOUT_SECONDS,
    REGISTERED,
    existing_identity,
    register,
    registration_offer,
)
from vibedpn.engine.ddns import URL_FILE as DDNS_URL_FILE
from vibedpn.engine.ddns import DdnsError
from vibedpn.engine.ddns import host_of as ddns_host
from vibedpn.engine.ddns import save_url as save_ddns_url
from vibedpn.engine.hostapd import (
    PASSPHRASE_MAX,
    PASSPHRASE_MIN,
    HostapdError,
    read_passphrase,
    write_passphrase,
)
from vibedpn.engine.myst import MystError, TequilaClient, render_stats
from vibedpn.engine.xray import XrayError, parse_share_link
from vibedpn.event_view import client_line, event_line
from vibedpn.tunnel_view import (
    qr_code,
    render_access_people,
    render_ddns,
    render_peer_traffic,
    render_peers,
)

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
    role: Role,
    peer_config: Path | None,
    endpoint: str | None,
    password_file: Path | None,
    lan_interface: str | None = None,
) -> None:
    """A flag of another role is a mistake, not something to ignore silently."""
    if lan_interface is not None and role is Role.VPS:
        raise _fail("--lan-interface is only used with --role home or client")
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
    lan_interface: str | None = None,
) -> Answers:
    """Ask only what cannot be detected or was not passed as a flag; fail early on known facts."""
    role = role or _ask_role()
    _check_flags_for_role(role, peer_config, endpoint, password_file, lan_interface)
    if role is not Role.VPS and facts.interface is None:
        raise _fail("no interface with a default route was found; connect the box to the LAN first")
    password = _read_password_file(password_file) if password_file else _ask_password()
    if role is Role.CLIENT and peer_config is None:
        peer_config = _ask_peer_config()
    if role is Role.VPS and endpoint is None and public_address(facts) is None:
        endpoint = _ask_endpoint()
    return Answers(role=role, password=password, peer_config=peer_config, endpoint=endpoint)


def _echo_network(config: Config) -> None:
    """What gateway mode and its access point mean for the owner, after init."""
    network = config.network
    if network is None or network.mode is not NetworkMode.GATEWAY:
        return
    typer.echo(
        f"Gateway mode: WAN {network.wan_interface}, LAN {network.lan_interface}"
        f" {network.lan_address}; the box hands out addresses on the LAN"
    )
    if network.wifi is not None:
        typer.echo(
            f"Wi-Fi {network.wifi.ssid!r}: the passphrase is in secrets/wifi-passphrase"
            " (`sudo vibedpn wifi show`)"
        )


def _wifi_answer(
    ssid: str | None, country: str | None, lan_interface: str | None, probe: HostProbe
) -> WifiConfig | None:
    """The access point asked by flags, checked before anything is written."""
    if ssid is None and country is None:
        return None
    if ssid is None or country is None:
        raise _fail("--wifi-ssid and --wifi-country go together")
    if lan_interface is None:
        raise _fail("--wifi-ssid needs --lan-interface: the radio interface that becomes the LAN")
    if not probe.is_wireless(lan_interface):
        raise _fail(f"{lan_interface} is not a wireless interface; the access point needs a radio")
    try:
        return WifiConfig(ssid=ssid, country=country)
    except ValidationError as exc:
        raise _fail(f"Wi-Fi: {exc.errors()[0]['msg']}") from None


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
    lan_interface: Annotated[
        str | None,
        typer.Option(
            help="Gateway mode: the LAN-side interface (with a static IPv4); the default-route"
            " interface becomes the WAN. Without it the box sits in the LAN on one port."
        ),
    ] = None,
    wifi_ssid: Annotated[
        str | None,
        typer.Option(
            help="Wi-Fi access point on the --lan-interface radio: the network name. The passphrase"
            " is generated into secrets/wifi-passphrase (`vibedpn wifi show`)."
        ),
    ] = None,
    wifi_country: Annotated[
        str | None,
        typer.Option(
            help="Country of the radio, ISO 3166-1 alpha-2 (with --wifi-ssid): the channels and"
            " power its law allows."
        ),
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
            interfaces=probe.interfaces(),
        )
    except DetectError as exc:
        raise _fail(str(exc)) from None
    if facts.interface is not None:
        detected = facts.interface
        typer.echo(f"Detected {detected.name}: {detected.address}/{detected.prefixlen}")
    for other in facts.interfaces:
        if facts.interface is None or other.name != facts.interface.name:
            typer.echo(f"Also {other.name}: {other.address}/{other.prefixlen} (--lan-interface)")
    wifi = _wifi_answer(wifi_ssid, wifi_country, lan_interface, probe)
    answers = replace(
        _collect_answers(role, peer_config, endpoint, password_file, facts, lan_interface),
        ui_variant=ui_variant,
        lan_interface=lan_interface,
        wifi=wifi,
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
    _echo_network(config)
    if config.network is not None and config.ui.enabled:
        typer.echo(f"Panel variant {config.ui.variant.value} (ui.variant in config.yaml)")
    typer.echo(f"Role {answers.role.value} configured. Next step: vibedpn up")


def _prepare(box_dir: Path, *, refresh: bool) -> Config:
    """Common start of every Compose command: a valid box, a usable Docker, a fresh ``.env``."""
    try:
        config = check_box(box_dir)
        preflight()
        if refresh:
            for created in ensure_country_secrets(box_dir, config):
                typer.echo(f"created {created} for the consumer of a new exit country")
            check_secrets(box_dir, config)
            refresh_countries(box_dir, config)
            refresh_wg_uplinks(box_dir, config)
            refresh_tor_bridges(box_dir, config)
            refresh_xray_config(box_dir, config)
            # last: .env carries the fingerprints of the files rendered above
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


def _inactive_services(box_dir: Path) -> list[str]:
    """Services of the profiles .env does not activate."""
    try:
        return stale_services(
            capture(compose_argv(box_dir, "config", "--services", all_profiles=True)),
            capture(compose_argv(box_dir, "config", "--services")),
        )
    except ComposeError as exc:
        raise _fail(str(exc)) from None


def _retire_stale(box_dir: Path) -> None:
    """Stop and remove containers of profiles the (fresh) .env no longer activates."""
    stale = _inactive_services(box_dir)
    if stale:
        _compose(box_dir, "rm", "--stop", "--force", *stale, all_profiles=True)


@app.command()
def up(box_dir: BoxDir = DEFAULT_BOX_DIR) -> None:
    """Start the box, or apply config.yaml: derive .env and recreate only what changed."""
    previous = read_env(box_dir / ENV_FILE)
    config = _prepare(box_dir, refresh=True)
    _ensure_apply_units(box_dir)
    active = config.digest_services()
    recreated = [
        service
        for service in recreated_services(previous, config.config_digests())
        if service in active
    ]
    if recreated:
        typer.echo(
            f"config.yaml changed for {', '.join(recreated)}:"
            " they are recreated, the other services keep running"
        )
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


UPDATE_UNIT = "vibedpn-update"
SYSTEMD_DIR = Path("/etc/systemd/system")
# Weekly at night with a spread, and a missed run is caught up after a power-off (systemd.timer(5)).
UPDATE_TIMER = """[Unit]
Description=VibeDPN weekly update (vibedpn update --timer)

[Timer]
OnCalendar=Sun *-*-* 04:00:00
RandomizedDelaySec=1h
Persistent=true

[Install]
WantedBy=timers.target
"""


class TimerSwitch(StrEnum):
    ON = "on"
    OFF = "off"


def _running_services(box_dir: Path) -> list[str]:
    try:
        services = parse_ps(capture(compose_argv(box_dir, "ps", "--format", "json")))
    except ComposeError as exc:
        raise _fail(str(exc)) from None
    return [item.service for item in services if item.state == "running"]


@app.command()
def backup(
    out: Annotated[
        Path | None,
        typer.Option(help="Archive to write; default backups/vibedpn-<time>.tar.gz in the box."),
    ] = None,
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """Archive config.yaml, .env, secrets/ and data/; the box pauses for the copy."""
    _prepare(box_dir, refresh=False)
    target = out or box_dir / BACKUPS_DIR / f"vibedpn-{stamp(time.time())}.tar.gz"
    running = _running_services(box_dir)
    if running:
        _compose(box_dir, "stop")
    try:
        names = create_archive(box_dir, target)
    except BackupError as exc:
        raise _fail(str(exc)) from None
    finally:
        if running:
            _compose(box_dir, "up", "-d")
    typer.echo(f"wrote {target} ({', '.join(names)}); it holds secrets: keep it private")


@app.command()
def restore(
    archive: Annotated[
        Path, typer.Argument(help="Archive from `vibedpn backup`.", exists=True, dir_okay=False)
    ],
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """Put a backup back: the box goes down, the current files move aside, nothing is deleted."""
    try:
        read_members(archive)
    except BackupError as exc:
        raise _fail(str(exc)) from None
    if (box_dir / CONFIG_FILE).exists():
        _prepare(box_dir, refresh=False)
        _compose(box_dir, "down", all_profiles=True)
    try:
        aside = restore_archive(box_dir, archive, time.time())
    except BackupError as exc:
        raise _fail(str(exc)) from None
    if aside is not None:
        typer.echo(f"the previous files are in {aside}")
    typer.echo("restored; check config.yaml, then: vibedpn up")


def _switch_update_timer(box_dir: Path, switch: TimerSwitch) -> None:
    service = SYSTEMD_DIR / f"{UPDATE_UNIT}.service"
    timer = SYSTEMD_DIR / f"{UPDATE_UNIT}.timer"
    systemctl = find_tool("systemctl")
    if systemctl is None:
        raise _fail("systemctl not found: the update timer needs systemd")
    try:
        if switch is TimerSwitch.ON:
            service.write_text(
                "[Unit]\nDescription=VibeDPN update\nAfter=docker.service network-online.target\n\n"
                f"[Service]\nType=oneshot\nExecStart={sys.executable} -m vibedpn update"
                f" --dir {box_dir.resolve()}\n",
                encoding="utf-8",
            )
            timer.write_text(UPDATE_TIMER, encoding="utf-8")
            commands = [["daemon-reload"], ["enable", "--now", timer.name]]
        else:
            commands = [["disable", "--now", timer.name]]
            for unit in (timer, service):
                unit.unlink(missing_ok=True)
            commands.append(["daemon-reload"])
    except PermissionError:
        raise _fail(f"cannot write {SYSTEMD_DIR}; run with sudo") from None
    for command in commands:
        if run([systemctl, *command]) != 0:
            raise _fail(f"systemctl {' '.join(command)} failed")
    typer.echo(f"automatic update: {switch.value}")


@app.command()
def update(
    timer: Annotated[
        TimerSwitch | None,
        typer.Option(help="Weekly automatic update by a systemd timer: on or off."),
    ] = None,
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """Update the checkout and the CLI (install.sh), pull the images, restart the box."""
    if timer is not None:
        _switch_update_timer(box_dir, timer)
        return
    config = _prepare(box_dir, refresh=False)
    installer = box_dir / "install.sh"
    if not (box_dir / ".git").is_dir() or not installer.is_file():
        raise _fail(f"{box_dir} is not a checkout made by install.sh; nothing to update")
    try:
        branch = capture(["git", "-C", str(box_dir), "rev-parse", "--abbrev-ref", "HEAD"]).strip()
        origin = capture(["git", "-C", str(box_dir), "remote", "get-url", "origin"]).strip()
    except ComposeError as exc:
        raise _fail(str(exc)) from None
    environment = {"VIBEDPN_DIR": str(box_dir), "VIBEDPN_BRANCH": branch, "VIBEDPN_REPO": origin}
    if (
        run(
            [
                "env",
                *(f"{key}={value}" for key, value in environment.items()),
                "bash",
                str(installer),
            ]
        )
        != 0
    ):
        raise _fail("install.sh failed; the box keeps running the previous version")
    _pull(box_dir)
    # the restart runs the freshly installed CLI, not this process with the old code loaded
    if run([sys.executable, "-m", "vibedpn", "restart", "--dir", str(box_dir)]) != 0:
        raise _fail("restart after the update failed; see `vibedpn doctor`")
    typer.echo(f"updated to the latest {branch} (role {config.role.value})")


def _pull(box_dir: Path) -> None:
    """Pull the images of the active services, and of every other service whose image this host
    keeps (compose.kept_services): a profile enabled after the update starts on current code."""
    # --ignore-pull-failures, not --ignore-buildable: the latter skips every service that has
    # a `build:` section, which is all of ours, so the box pulled only the third-party images
    # and kept running its own containers on the code they were built with (knowledge
    # linux/boxBackup.md). A service whose image is not published is the failure this flag forgives.
    _compose(box_dir, "pull", "--ignore-pull-failures")
    inactive = _inactive_services(box_dir)
    if not inactive:
        return
    try:
        kept = kept_services(
            capture(compose_argv(box_dir, "config", "--format", "json", all_profiles=True)),
            capture(IMAGE_LISTING),
            inactive,
        )
    except ComposeError as exc:
        raise _fail(str(exc)) from None
    if kept:
        _compose(box_dir, "pull", "--ignore-pull-failures", *kept, all_profiles=True)


def _routing_line(config: Config) -> str:
    if config.routing is None:
        return "routing: -"
    return (
        f"routing: mode={config.routing.mode.value}"
        f" default_upstream={config.routing.default_upstream}"
        f" failopen={str(config.routing.failopen).lower()}"
    )


class SwitchableMode(StrEnum):
    """Modes the router implements."""

    OFF = RoutingMode.OFF.value
    FULL = RoutingMode.FULL.value
    SMART = RoutingMode.SMART.value


def _switch_routing(
    box_dir: Path, *, mode: RoutingMode | None = None, upstream: str | None = None
) -> None:
    """Change routing through core when it runs: config.yaml, the router and AdGuard follow live
    and nothing restarts. Without core the file is changed and applies at `vibedpn up`."""
    config = _prepare(box_dir, refresh=False)
    try:
        view = core_api.set_routing(config.api.port, mode, upstream)
    except core_api.CoreUnreachableError:
        pass
    except (core_api.CoreNoAnswerError, core_api.RoutingRequestError) as exc:
        raise _fail(str(exc)) from None
    else:
        note = (
            "router applied; AdGuard catches up at the next start of core"
            if view.adguard == "pending"
            else "applied live, nothing restarted"
        )
        typer.echo(f"routing: mode={view.mode} default_upstream={view.default_upstream} ({note})")
        return
    try:
        saved, changed = set_routing(box_dir / CONFIG_FILE, mode=mode, upstream=upstream)
    except ConfigEditError as exc:
        raise _fail(str(exc)) from None
    if not changed:
        typer.echo(f"{_routing_line(saved)} (already set)")
        return
    typer.echo(f"{_routing_line(saved)} (saved; core is not running, applies at `vibedpn up`)")


@app.command()
def mode(
    value: Annotated[
        SwitchableMode,
        typer.Argument(help="off: LAN direct; full: all via uplink; smart: by routing.domains."),
    ],
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """Switch routing.mode of the LAN router and apply it."""
    _switch_routing(box_dir, mode=RoutingMode(value.value))


@app.command()
def upstream(
    value: Annotated[
        str,
        typer.Argument(help="The uplink of routing.mode full: vps, dpn, tor, or wg-<name>."),
    ],
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """Switch routing.default_upstream and apply it."""
    _switch_routing(box_dir, upstream=value)


def _ensure_apply_units(box_dir: Path) -> None:
    """The systemd units that apply a change made in the panel (decision 26), kept current by every
    `up`. A host without systemd, or `up` without root, runs without them: the panel then says the
    change waits, and `vibedpn up` by hand applies it."""
    systemctl = find_tool("systemctl")
    if systemctl is None or os.geteuid() != 0:
        return
    changed = False
    try:
        for name, text in render_units(box_dir.resolve(), sys.executable).items():
            unit = SYSTEMD_DIR / name
            if not unit.is_file() or unit.read_text(encoding="utf-8") != text:
                unit.write_text(text, encoding="utf-8")
                changed = True
    except OSError as exc:
        typer.secho(
            f"cannot write the units that apply panel changes: {exc.strerror or exc}",
            fg=typer.colors.YELLOW,
            err=True,
        )
        return
    path_unit = f"{APPLY_UNIT}.path"
    if changed:
        run([systemctl, "daemon-reload"])
    if changed or run([systemctl, "is-enabled", "--quiet", path_unit]) != 0:
        run([systemctl, "enable", "--now", path_unit])


@app.command()
def apply(box_dir: BoxDir = DEFAULT_BOX_DIR) -> None:
    """Run `up` for a change the panel asked for (the systemd unit vibedpn-apply runs this)."""
    data_dir = box_dir / BOX_DATA_DIR
    while True:
        requested = read_request(data_dir)
        last = read_result(data_dir)
        if requested is None or (last is not None and last.requested_at >= requested):
            return  # nothing asked, or already applied
        try:
            up(box_dir)
            ok, message = True, "applied"
        except typer.Exit as exc:
            ok = exc.exit_code == 0
            message = (
                "applied"
                if ok
                else f"vibedpn up failed (exit {exc.exit_code}); journalctl -u {APPLY_UNIT}"
            )
        write_result(data_dir, ApplyResult(requested, time.time(), ok, message))
        if not ok:
            raise typer.Exit(EXIT_USER_ERROR)
        # a change made while `up` ran was asked for after `requested`: the loop applies it too


EVENTS_DEFAULT_HOURS = 24.0
EVENTS_DEFAULT_LIMIT = 200


@app.command()
def events(
    kind: Annotated[
        str | None, typer.Option("--kind", help="Only this kind: wifi or uplink.")
    ] = None,
    hours: Annotated[
        float, typer.Option("--hours", help="How far back to look, in hours.")
    ] = EVENTS_DEFAULT_HOURS,
    limit: Annotated[
        int, typer.Option("--limit", help="At most this many events, newest first.")
    ] = EVENTS_DEFAULT_LIMIT,
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """The event journal of the box: Wi-Fi clients coming and going, uplinks up and down."""
    config = _lan_box(box_dir)
    since = time.time() - hours * 3600
    found = _core_call(
        lambda: core_api.list_events(config.api.port, kind=kind, since=since, limit=limit)
    )
    if not found:
        typer.echo(f"no events in the last {hours:g} h")
    for item in reversed(found):  # oldest first reads like a log
        typer.echo(event_line(item))


uplink_app = typer.Typer(
    help="Own exits by a ready WireGuard file, one per name (docs/manuals/wgUplink.md).",
    no_args_is_help=True,
)
app.add_typer(uplink_app, name="uplink")


def _refresh_file_digests(box_dir: Path, config: Config) -> None:
    """After replacing a file a gateway reads: this command runs with sudo and can read it, while
    a later `vibedpn up` without sudo cannot, and would keep the fingerprint of the old one."""
    try:
        refresh_env(box_dir, config)
    except ComposeError as exc:
        raise _fail(str(exc)) from None


def _wg_conf_path(box_dir: Path, name: str) -> Path:
    if not WG_UPLINK_NAME.fullmatch(name):
        raise _fail(f"{name!r} is not a usable name: lowercase letters, digits and '-', up to 24")
    return box_dir / SECRETS_DIR / wg_uplink_file(name)


@uplink_app.command("add")
def uplink_add(
    name: Annotated[str, typer.Argument(help="Name of the exit: a-z, 0-9 and '-'.")],
    peer_config: Annotated[Path, typer.Argument(help="The WireGuard .conf of the provider.")],
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """Take a ready WireGuard file as an exit of this box; `vibedpn up` starts it."""
    target = _wg_conf_path(box_dir, name)
    try:
        text = read_peer_config(peer_config)
    except BootstrapError as exc:
        raise _fail(str(exc)) from None
    try:
        target.parent.mkdir(mode=SECRET_DIR_MODE, exist_ok=True)
        write_private(target, text)
    except OSError as exc:
        raise _fail(f"cannot write {target}: {exc.strerror}; run with sudo?") from None
    try:
        config, _changed = set_wg_uplink(box_dir / CONFIG_FILE, name)
    except ConfigEditError as exc:
        raise _fail(str(exc)) from None
    _refresh_file_digests(box_dir, config)
    typer.echo(f"uplink wg-{name}: {target} saved; `vibedpn up`, then `vibedpn upstream wg-{name}`")


@uplink_app.command("rm")
def uplink_rm(
    name: Annotated[str, typer.Argument(help="Name of the exit to drop.")],
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """Drop a named exit and its file: the key of an exit the box no longer has does not stay."""
    try:
        remove_wg_uplink(box_dir / CONFIG_FILE, name)
    except WgUplinkNotFoundError as exc:
        raise _fail(str(exc)) from None
    except ConfigEditError as exc:
        raise _fail(str(exc)) from None
    removed = _wg_conf_path(box_dir, name)
    removed.unlink(missing_ok=True)
    typer.echo(f"uplink wg-{name} removed with {removed}; `vibedpn up` stops its container")


@uplink_app.command("show")
def uplink_show(box_dir: BoxDir = DEFAULT_BOX_DIR) -> None:
    """The named WireGuard exits of config.yaml and whether their files are in place."""
    config = check_box(box_dir)
    if not config.upstreams.wg:
        typer.echo("no WireGuard exits (vibedpn uplink add <name> <file.conf>)")
        return
    for name in sorted(config.upstreams.wg):
        uplink = config.upstreams.wg[name]
        state = "enabled" if uplink.enabled else "disabled"
        path = box_dir / SECRETS_DIR / wg_uplink_file(name)
        file_state = "file in place" if path.is_file() else f"NO FILE at {path}"
        typer.echo(f"wg-{name}  {state}  ({file_state})")


xray_app = typer.Typer(
    help="Uplink xray: a masking transport by your own share link (docs/manuals/xrayUplink.md).",
    no_args_is_help=True,
)
app.add_typer(xray_app, name="xray")


@xray_app.command("enable")
def xray_enable(
    link_file: Annotated[
        Path | None,
        typer.Option("--link-file", help="File with the vless:// link; without it, asked here."),
    ] = None,
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """Take a share link as the masking exit of this box; `vibedpn up` starts its gateway.

    The link is never an argument: it carries the credentials of the server, and an argument lands
    in the shell history and in `ps` for every user of the box.
    """
    if link_file is not None:
        try:
            link = link_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise _fail(f"cannot read {link_file}: {exc.strerror}") from None
    else:
        link = typer.prompt("Share link (vless://…)")
    try:
        server = parse_share_link(link)
    except XrayError as exc:
        raise _fail(str(exc)) from None
    target = box_dir / SECRETS_DIR / XRAY_LINK_FILE
    try:
        target.parent.mkdir(mode=SECRET_DIR_MODE, exist_ok=True)
        write_private(target, link.strip() + "\n")
    except OSError as exc:
        raise _fail(f"cannot write {target}: {exc.strerror}; run with sudo?") from None
    config = _set_xray(box_dir, True)
    try:
        refresh_xray_config(box_dir, config)
    except ComposeError as exc:
        raise _fail(str(exc)) from None
    _refresh_file_digests(box_dir, config)
    typer.echo(f"uplink xray enabled: {server.endpoint}, {server.security}; `vibedpn up`, then:")
    typer.echo(
        "  vibedpn rule add <domain> xray   (smart mode), or vibedpn upstream xray (full mode)"
    )


@xray_app.command("disable")
def xray_disable(box_dir: BoxDir = DEFAULT_BOX_DIR) -> None:
    """Turn uplink xray off; rules and devices that name it keep the config from validating."""
    _set_xray(box_dir, False)
    typer.echo("uplink xray disabled; `vibedpn up` stops its gateway")


@xray_app.command("show")
def xray_show(box_dir: BoxDir = DEFAULT_BOX_DIR) -> None:
    """Whether uplink xray is on and which server it uses — without a word of its credentials."""
    config = check_box(box_dir)
    state = "on" if config.upstreams.xray.enabled else "off"
    path = box_dir / SECRETS_DIR / XRAY_LINK_FILE
    try:
        server = parse_share_link(path.read_text(encoding="utf-8"))
    except OSError:
        typer.echo(f"uplink xray {state}; no link at {path} (vibedpn xray enable)")
        return
    except XrayError as exc:
        typer.echo(f"uplink xray {state}; the link at {path} is unusable: {exc}")
        return
    transport = f"{server.network}/{server.security}"
    name = f" ({server.remark})" if server.remark else ""
    typer.echo(f"uplink xray {state}: {server.endpoint} over {transport}{name}")


def _set_xray(box_dir: Path, enabled: bool) -> Config:
    try:
        config, _changed = set_xray_uplink(box_dir / CONFIG_FILE, enabled)
    except ConfigEditError as exc:
        raise _fail(str(exc)) from None
    return config


tor_app = typer.Typer(
    help="Uplink tor: a free exit through Tor bridges, TCP only (docs/manuals/torUplink.md).",
    no_args_is_help=True,
)
app.add_typer(tor_app, name="tor")


def _set_tor(box_dir: Path, enabled: bool) -> Config:
    try:
        config, _changed = set_tor_uplink(box_dir / CONFIG_FILE, enabled)
    except ConfigEditError as exc:
        raise _fail(str(exc)) from None
    return config


@tor_app.command("enable")
def tor_enable(box_dir: BoxDir = DEFAULT_BOX_DIR) -> None:
    """Turn uplink tor on; `vibedpn up` starts its gateway, which bootstraps in a minute or two."""
    config = _set_tor(box_dir, True)
    count = len(config.upstreams.tor.bridges)
    typer.echo(
        f"uplink tor enabled with {count} bridges; `vibedpn up`, then send sites through it:"
    )
    typer.echo(
        "  vibedpn rule add <domain> tor   (smart mode), or vibedpn upstream tor (full mode)"
    )


@tor_app.command("disable")
def tor_disable(box_dir: BoxDir = DEFAULT_BOX_DIR) -> None:
    """Turn uplink tor off; rules and devices that still name it keep the config from validating."""
    _set_tor(box_dir, False)
    typer.echo("uplink tor disabled; `vibedpn up` stops its gateway")


@tor_app.command("show")
def tor_show(box_dir: BoxDir = DEFAULT_BOX_DIR) -> None:
    """Whether uplink tor is on and which bridges it uses."""
    config = check_box(box_dir)
    tor = config.upstreams.tor
    typer.echo(f"tor  {'enabled' if tor.enabled else 'disabled'}  {len(tor.bridges)} bridges")
    for line in tor.bridges:
        words = line.split()
        typer.echo(f"  {words[0]} {words[1]}")


dpn_app = typer.Typer(
    help="Uplink dpn: the exit through the Mysterium network.", no_args_is_help=True
)
app.add_typer(dpn_app, name="dpn")
wifi_app = typer.Typer(help="The Wi-Fi access point of gateway mode.", no_args_is_help=True)
app.add_typer(wifi_app, name="wifi")


@wifi_app.command("clients")
def wifi_clients(box_dir: BoxDir = DEFAULT_BOX_DIR) -> None:
    """Who is on the access point now, for how long, and at what signal."""
    config = _lan_box(box_dir)
    clients = _core_call(lambda: core_api.list_wifi_clients(config.api.port))
    if not clients:
        typer.echo("no Wi-Fi clients connected")
    for client in clients:
        typer.echo(client_line(client))


@wifi_app.command("show")
def wifi_show(box_dir: BoxDir = DEFAULT_BOX_DIR) -> None:
    """Print the network name and the passphrase devices join with (secrets/ is root-only)."""
    try:
        config = check_box(box_dir)
    except ComposeError as exc:
        raise _fail(str(exc)) from None
    wifi = config.network.wifi if config.network is not None else None
    if wifi is None:
        raise _fail("this box serves no Wi-Fi: network.wifi is not set in config.yaml")
    try:
        passphrase = read_passphrase(box_dir / SECRETS_DIR)
    except HostapdError as exc:
        raise _fail(str(exc)) from None
    typer.echo(f"ssid: {wifi.ssid}")
    typer.echo(f"passphrase: {passphrase}")
    typer.echo(
        f"security: {wifi.security.value}, band {wifi.band.value} GHz, channel {wifi.channel}"
    )


@app.command("password")
def password(box_dir: BoxDir = DEFAULT_BOX_DIR) -> None:
    """Set the panel password (VibeDPN UI and the node's NodeUI): asked twice without echo."""
    config = _prepare(box_dir, refresh=False)
    try:
        set_panel_password(box_dir, config, _ask_password())
    except BootstrapError as exc:
        raise _fail(str(exc)) from None
    # the panel checks secrets/htpasswd on every sign-in; the node reads its hash only at start
    if config.provider.enabled:
        _compose(box_dir, "up", "-d", "--force-recreate", "myst-provider")
        typer.echo("panel password changed: VibeDPN UI at once, NodeUI after the node restarted")
    else:
        typer.echo("panel password changed: the next sign-in uses it")


@wifi_app.command("passphrase")
def wifi_passphrase(box_dir: BoxDir = DEFAULT_BOX_DIR) -> None:
    """Set your own Wi-Fi passphrase: asked twice without echo, then the access point restarts."""
    config = _prepare(box_dir, refresh=False)
    wifi = config.network.wifi if config.network is not None else None
    if wifi is None:
        raise _fail("this box serves no Wi-Fi: network.wifi is not set in config.yaml")
    value = typer.prompt(
        f"New passphrase of Wi-Fi {wifi.ssid!r} ({PASSPHRASE_MIN}-{PASSPHRASE_MAX} characters)",
        hide_input=True,
        confirmation_prompt=True,
    )
    try:
        changed = write_passphrase(box_dir / SECRETS_DIR, value)
    except HostapdError as exc:
        raise _fail(str(exc)) from None
    if not changed:
        typer.echo(f"Wi-Fi {wifi.ssid!r} already has this passphrase: nothing to restart")
        return
    # core renders hostapd.conf from secrets/ at its start, hostapd reads that file at its own
    _compose(box_dir, "up", "-d", "--force-recreate", "core", "hostapd")
    typer.echo(f"Wi-Fi {wifi.ssid!r}: the new passphrase is in use, devices join with it now")


WEI_IN_MYST = 10**18


def _myst(wei: str) -> str:
    """Wei as the owner reads it: MYST with four decimals; an unusable value stays as it came."""
    try:
        return f"{int(wei) / WEI_IN_MYST:.4f} MYST"
    except ValueError:
        return f"{wei} wei"


@dpn_app.command("register")
def dpn_register(
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation.")] = False,
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """Register the consumer identity in the Mysterium network — the step that may cost money.

    The box never does this by itself (docs/decisions.md, 4): registration is a transaction on the
    network, and paying is the owner's decision. The command shows what it would cost, asks, and
    only then asks the node to register.
    """
    config = _prepare(box_dir, refresh=False)
    if not config.upstreams.dpn.enabled:
        raise _fail("uplink dpn is off: enable it in config.yaml and `vibedpn up` first")
    client = TequilaClient(base_url=CONSUMER_TEQUILAPI, timeout=CONSUMER_TIMEOUT_SECONDS)
    try:
        identity = existing_identity(client)
        if identity is None:
            raise _fail("the node has no identity yet: `vibedpn up` and wait for its first round")
        offer = registration_offer(client, identity)
    except MystError as exc:
        raise _fail(f"the consumer node did not answer: {exc}") from None

    typer.echo(f"identity: {offer.identity}")
    typer.echo(f"registration: {offer.status}")
    if offer.status == REGISTERED:
        typer.echo("already registered; nothing to pay and nothing to do")
        return
    if offer.free:
        typer.echo("the network registers this identity for free")
    else:
        typer.echo(f"fee: {_myst(offer.fee_wei)}; balance: {_myst(offer.balance_wei)}")
        if not offer.affordable:
            typer.echo(f"top up {offer.channel_address} with MYST on Polygon first (see README)")
            raise typer.Exit(EXIT_USER_ERROR)
    if not yes and not typer.confirm("Register this identity now?"):
        raise typer.Exit(EXIT_USER_ERROR)
    try:
        result = register(client, identity)
    except MystError as exc:
        raise _fail(str(exc)) from None
    typer.echo(f"registration {result}; `vibedpn status` shows it when the network confirms")


ANY_COUNTRY = "any"


@dpn_app.command("country")
def dpn_country(
    code: Annotated[str, typer.Argument(help="ISO 3166-1 alpha-2 code, or `any`.")],
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """Pin uplink dpn to a country; core reconnects the consumer on its next round."""
    config = _prepare(box_dir, refresh=False)
    country = None if code.lower() == ANY_COUNTRY else code
    try:
        view = core_api.set_dpn_country(config.api.port, country)
    except core_api.CoreUnreachableError:
        raise _fail("core is not running: `vibedpn up` first") from None
    except (core_api.CoreNoAnswerError, core_api.RoutingRequestError) as exc:
        raise _fail(str(exc)) from None
    typer.echo(f"dpn country: {view.country or ANY_COUNTRY} (the consumer follows within a minute)")


@app.command()
def status(box_dir: BoxDir = DEFAULT_BOX_DIR) -> None:
    """Role and routing from config.yaml, then the state of every container."""
    config = _prepare(box_dir, refresh=False)
    typer.echo(f"role: {config.role.value}")
    if config.routing is not None:
        typer.echo(_routing_line(config))
    wg_keys = (f"wg-{name}" for name in sorted(config.upstreams.wg))
    keys = [*(upstream.value for upstream in Upstream), *wg_keys]
    uplinks = [key for key in keys if config.upstreams.is_key_enabled(key)]
    typer.echo(f"uplinks: {', '.join(uplinks) or '-'}")
    for line in _router_lines(config):
        typer.echo(line)
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


def _router_lines(config: Config) -> list[str]:
    """The uplinks in use as core sees them, and one line when the kill switch holds the LAN."""
    if config.routing is None:
        return []
    try:
        status = core_api.fetch_status(config.api.port)
    except core_api.CoreUnreachableError:
        return ["router: core is not running (run `vibedpn up`)"]
    except (core_api.CoreNoAnswerError, core_api.RoutingRequestError) as exc:
        return [f"router: {exc}"]
    answers = {True: "answers", False: "does not answer", None: "not probed yet"}
    lines = [
        f"uplink {item.name}: gateway {answers[item.gateway_alive]}"
        for item in status.uplinks
        if item.in_use
    ]
    if status.lan_without_exit:
        lines.append(
            f"lan exit: none — the {status.default_upstream} gateway does not answer and"
            " failopen is false, the kill switch holds the LAN"
        )
    return lines


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
rule_app = typer.Typer(
    help="Domain rules of routing.mode smart: which channel each site takes.",
    no_args_is_help=True,
)
app.add_typer(rule_app, name="rule")
dns_app = typer.Typer(
    help="The DNS journal of the LAN devices (the sniffer).", no_args_is_help=True
)
app.add_typer(dns_app, name="dns")
lists_app = typer.Typer(
    help="Ready domain lists by URL for routing.mode smart: a channel for all their domains.",
    no_args_is_help=True,
)
app.add_typer(lists_app, name="lists")
WATCH_SECONDS = 1.0


def journal_line(entry: JournalEntryView) -> str:
    stamp = time.strftime("%H:%M:%S", time.localtime(entry.time))
    via = entry.channel.removeprefix("smart_") if entry.channel != "direct" else "direct"
    note = f"  learned: follows {entry.learned_from}" if entry.learned_from else ""
    cached = " cached" if entry.cached else ""
    return f"{stamp}  {entry.qtype:<5} {entry.name}  -> {via}{cached}{note}"


@dns_app.command("watch")
def dns_watch(
    device: Annotated[str, typer.Argument(help="The device: its IPv4 address or its MAC.")],
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """Show what a device asks, live, and which channel each name takes; Ctrl+C stops."""
    config = _lan_box(box_dir)
    client = device
    if ":" in device:
        devices = _core_call(lambda: core_api.list_devices(config.api.port))
        found = next(
            (item for item in devices if item.mac and item.mac.lower() == device.lower()), None
        )
        if found is None or found.ip is None:
            raise _fail(f"no LAN device with MAC {device} and an address")
        client = str(found.ip)
    typer.echo(f"DNS of {client} (Ctrl+C to stop)")
    since = 0.0
    try:
        while True:
            # the cursor is fixed per round: partial binds it now, not when called
            batch = _core_call(partial(core_api.journal, config.api.port, client, since))
            for entry in batch:
                typer.echo(journal_line(entry))
                since = max(since, entry.time)
            time.sleep(WATCH_SECONDS)
    except KeyboardInterrupt:
        typer.echo("")


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
    except (
        PeerRequestError,
        DeviceRequestError,
        core_api.RuleRequestError,
        core_api.EventRequestError,
        core_api.AccessRequestError,
    ) as exc:
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


@peer_app.command("traffic")
def peer_traffic(
    since: Annotated[
        str | None,
        typer.Option("--since", help="Count from this day (YYYY-MM-DD); by default, all of it."),
    ] = None,
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """How much every peer has used. The totals survive restarts: the counters of the interface
    start from zero at every boot, and core adds only what is new to a total of its own."""
    config = _vps_box(box_dir)
    totals = _core_call(lambda: core_api.list_peer_traffic(config.api.port, since))
    for line in render_peer_traffic(totals, since):
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


access_app = typer.Typer(
    help="The access server: links for your people, on any role (docs/manuals/accessServer.md).",
    no_args_is_help=True,
)
app.add_typer(access_app, name="access")
ddns_app = typer.Typer(
    help="A DNS name that follows the public address of this box (docs/manuals/accessServer.md).",
    no_args_is_help=True,
)
app.add_typer(ddns_app, name="ddns")

PersonName = Annotated[
    str, typer.Argument(help="Name of the person: 1-32 lowercase letters, digits and hyphens.")
]
LinkOut = Annotated[
    Path | None,
    typer.Option(
        "--out",
        dir_okay=False,
        help="Write the link here (mode 600) instead of printing it with its QR code.",
    ),
]


def _any_box(box_dir: Path) -> Config:
    try:
        return check_box(box_dir)
    except ComposeError as exc:
        raise _fail(str(exc)) from None


def _set_access(
    box_dir: Path,
    *,
    enabled: bool,
    address: str | None = None,
    port: int | None = None,
    target: str | None = None,
) -> Config:
    try:
        config, _changed = set_access(
            box_dir / CONFIG_FILE, enabled=enabled, address=address, port=port, target=target
        )
    except ConfigEditError as exc:
        raise _fail(str(exc)) from None
    return config


@access_app.command("enable")
def access_enable(
    address: Annotated[
        str | None,
        typer.Option(
            "--address",
            help="The name your people dial: one that follows this box (vibedpn ddns set),"
            " or the public address of a VPS.",
        ),
    ] = None,
    port: Annotated[
        int | None, typer.Option("--port", help="TCP port of the server; 443 unless it is taken.")
    ] = None,
    target: Annotated[
        str | None,
        typer.Option("--target", help="The cover site REALITY borrows its handshake from."),
    ] = None,
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """Turn the access server on; `vibedpn up` starts it."""
    config = _set_access(box_dir, enabled=True, address=address, port=port, target=target)
    typer.echo(
        f"access server enabled: {config.access_address()}:{config.access.port},"
        f" cover site {config.access.target}"
    )
    if config.network is not None:
        typer.echo(
            f"forward TCP {config.access.port} on your router to this box"
            " (docs/manuals/accessServer.md)"
        )
    typer.echo("`vibedpn up`, then: vibedpn access add <name>")


@access_app.command("disable")
def access_disable(box_dir: BoxDir = DEFAULT_BOX_DIR) -> None:
    """Turn the access server off; its people and their links are kept for the next time."""
    _set_access(box_dir, enabled=False)
    typer.echo("access server disabled; `vibedpn up` stops it")


@access_app.command("list")
def access_list(
    since: Annotated[
        str | None,
        typer.Option("--since", help="Count from this day (YYYY-MM-DD); by default, all of it."),
    ] = None,
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """The server and its people with what they used; the totals survive restarts."""
    config = _any_box(box_dir)
    view = _core_call(lambda: core_api.get_access(config.api.port, since))
    for line in render_access_people(view, since):
        typer.echo(line)


@access_app.command("add")
def access_add(
    name: PersonName,
    out: LinkOut = None,
    force: Force = False,
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """Add a person: their link and its QR code, applied to the running server at once."""
    config = _any_box(box_dir)
    link = _core_call(lambda: core_api.add_person(config.api.port, name))
    _deliver_link(link, out, force=force)


@access_app.command("link")
def access_link(
    name: PersonName,
    out: LinkOut = None,
    force: Force = False,
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """Print a person's link again with its QR code, or write it with --out."""
    config = _any_box(box_dir)
    link = _core_call(lambda: core_api.person_link(config.api.port, name))
    _deliver_link(link, out, force=force)


@access_app.command("rm")
def access_rm(
    name: PersonName,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation.")] = False,
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """Remove a person: their link stops working at once, nobody else is disconnected."""
    config = _any_box(box_dir)
    if not yes and not typer.confirm(f"Remove {name}? Their link stops working"):
        raise typer.Exit(EXIT_USER_ERROR)
    _core_call(lambda: core_api.remove_person(config.api.port, name))
    typer.echo(f"removed {name}")


def _deliver_link(link: AccessLink, out: Path | None, *, force: bool) -> None:
    """Print the link with its QR code, or write it to a file of its own."""
    if out is None:
        typer.echo(link.link)
        typer.echo(qr_code(link.link), nl=False)
        typer.echo(
            f"Give {link.name} this link or code: a phone app with VLESS/REALITY imports it"
            " (docs/manuals/accessServer.md)."
        )
        return
    # The link lets its holder in: never write it through a link that points somewhere else, and
    # never into an existing file whose mode would apply to it first.
    if out.is_symlink():
        raise _fail(f"{out} is a symlink; write the link to a plain path")
    if out.exists() and not force:
        raise _fail(f"{out} already exists; pass --force to overwrite it")
    try:
        write_private(out, link.link + "\n")
    except OSError as exc:
        raise _fail(f"cannot write {out}: {exc.strerror}") from None
    typer.echo(f"wrote {out}: the link of {link.name}; it lets its holder in")


@ddns_app.command("set")
def ddns_set(
    url_file: Annotated[
        Path | None,
        typer.Option("--url-file", help="File with the update URL; without it, asked here."),
    ] = None,
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """Take the update URL of your DDNS service and turn ddns on; `vibedpn up` starts it.

    The URL is never an argument: it carries a token, and an argument lands in the shell history
    and in `ps` for every user of the box.
    """
    if url_file is not None:
        try:
            url = url_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise _fail(f"cannot read {url_file}: {exc.strerror}") from None
    else:
        url = typer.prompt("Update URL (https://…)", hide_input=True)
    secrets = box_dir / SECRETS_DIR
    try:
        secrets.mkdir(mode=SECRET_DIR_MODE, exist_ok=True)
        saved = save_ddns_url(secrets, url)
    except DdnsError as exc:
        raise _fail(str(exc)) from None
    except OSError as exc:
        raise _fail(
            f"cannot write {secrets / DDNS_URL_FILE}: {exc.strerror}; run with sudo?"
        ) from None
    _set_ddns(box_dir, True)
    typer.echo(f"ddns enabled: {ddns_host(saved)}; `vibedpn up`, then `vibedpn ddns show`")


@ddns_app.command("show")
def ddns_show(box_dir: BoxDir = DEFAULT_BOX_DIR) -> None:
    """Which service, the public address, and how the last call went — never the URL itself."""
    config = _any_box(box_dir)
    view = _core_call(lambda: core_api.get_ddns(config.api.port))
    for line in render_ddns(view):
        typer.echo(line)


@ddns_app.command("off")
def ddns_off(box_dir: BoxDir = DEFAULT_BOX_DIR) -> None:
    """Turn ddns off; the update URL is kept for the next `vibedpn ddns set`."""
    _set_ddns(box_dir, False)
    typer.echo("ddns disabled; `vibedpn up` stops it")


def _set_ddns(box_dir: Path, enabled: bool) -> Config:
    try:
        config, _changed = set_ddns(box_dir / CONFIG_FILE, enabled)
    except ConfigEditError as exc:
        raise _fail(str(exc)) from None
    return config


def _lan_box(box_dir: Path) -> Config:
    try:
        config = check_box(box_dir)
    except ComposeError as exc:
        raise _fail(str(exc)) from None
    if config.network is None:
        raise _fail(f"LAN devices live on a box with a LAN; this box has role {config.role.value}")
    return config


DeviceId = Annotated[str, typer.Argument(help="The device: its MAC, or its IPv4 address.")]


@rule_app.command("learned")
def rule_learned(box_dir: BoxDir = DEFAULT_BOX_DIR) -> None:
    """CDNs that follow a site: learned from the DNS of the devices, or from CNAME chains."""
    config = _lan_box(box_dir)
    names = _core_call(lambda: core_api.learned_names(config.api.port))
    if not names:
        typer.echo("nothing learned yet")
    for item in names:
        typer.echo(f"{item.name}  follows {item.parent}  ({item.source}, seen {item.hits}x)")


@rule_app.command("forget")
def rule_forget(
    name: Annotated[str, typer.Argument(help="A learned CDN name.")],
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """Forget a learned CDN: it goes direct again until it is learned anew."""
    config = _lan_box(box_dir)
    _core_call(lambda: core_api.forget_learned(config.api.port, name))
    typer.echo(f"{name}: forgotten, goes direct")


def render_domain_list(item: DomainListView) -> str:
    """One line of `vibedpn lists show`: the channel, the domains in use and their age."""
    country = f" {item.country or item.uplink}" if item.country or item.uplink else ""
    if item.fetched_at is None:
        copy = "no copy yet" if item.error else "fetching"
    else:
        fetched = time.strftime("%Y-%m-%d %H:%M", time.localtime(item.fetched_at))
        copy = f"{item.domains} domains, fetched {fetched}"
    error = f" — {item.error}" if item.error else ""
    return f"{item.url}  {item.via}{country}  ({copy}){error}"


@lists_app.command("show")
def lists_show(box_dir: BoxDir = DEFAULT_BOX_DIR) -> None:
    """The domain lists of routing.lists with their channel and the copy core uses."""
    config = _lan_box(box_dir)
    items = _core_call(lambda: core_api.list_domain_lists(config.api.port))
    if not items:
        typer.echo("no domain lists (vibedpn lists add <url> vps|dpn|tor|direct)")
    for item in items:
        typer.echo(render_domain_list(item))


@lists_app.command("add")
def lists_add(
    url: Annotated[str, typer.Argument(help="An http(s) URL of a text list of domains.")],
    via: Annotated[DomainVia, typer.Argument(help="vps | dpn | wg | tor | direct.")],
    country: Annotated[
        str | None, typer.Option("--country", help="Exit country of via dpn (ISO code).")
    ] = None,
    uplink: Annotated[
        str | None, typer.Option("--uplink", help="The exit of via wg: a name of upstreams.wg.")
    ] = None,
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """Give every domain of a list a channel; a list with that URL gets the new channel."""
    config = _lan_box(box_dir)
    update = DomainListUpdate(url=url, via=via.value, country=country, uplink=uplink)
    item = _core_call(lambda: core_api.set_domain_list(config.api.port, update))
    country_text = f" {item.country or item.uplink}" if item.country or item.uplink else ""
    typer.echo(f"{item.url}: via {item.via}{country_text}, core fetches it within a minute")


@lists_app.command("rm")
def lists_rm(
    url: Annotated[str, typer.Argument(help="The URL of the list that goes.")],
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """Remove a domain list: its domains go direct in smart again."""
    config = _lan_box(box_dir)
    _core_call(lambda: core_api.remove_domain_list(config.api.port, url))
    typer.echo(f"{url}: list removed")


net_app = typer.Typer(
    help="Address networks of routing.mode smart, for apps that connect by address (Telegram).",
    no_args_is_help=True,
)
app.add_typer(net_app, name="net")


@net_app.command("list")
def net_list(box_dir: BoxDir = DEFAULT_BOX_DIR) -> None:
    """The network rules of routing.mode smart: each network with its channel."""
    config = _lan_box(box_dir)
    rules = _core_call(lambda: core_api.list_network_rules(config.api.port))
    if not rules:
        typer.echo("no network rules (vibedpn net add <a.b.c.d/nn> vps|dpn|tor|direct)")
    for rule in rules:
        extra = f" {rule.country or rule.uplink}" if rule.country or rule.uplink else ""
        typer.echo(f"{rule.network}  via {rule.via}{extra}")


@net_app.command("add")
def net_add(
    network: Annotated[str, typer.Argument(help="An IPv4 network, a.b.c.d/nn.")],
    via: Annotated[DomainVia, typer.Argument(help="vps | dpn | wg | tor | direct.")],
    country: Annotated[
        str | None, typer.Option("--country", help="Exit country of via dpn (ISO code).")
    ] = None,
    uplink: Annotated[
        str | None, typer.Option("--uplink", help="The exit of via wg: a name of upstreams.wg.")
    ] = None,
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """Give a network its channel in routing.mode smart; a rule for the same network is replaced."""
    config = _lan_box(box_dir)
    update = NetworkRuleUpdate(network=network, via=via.value, country=country, uplink=uplink)
    rule = _core_call(lambda: core_api.set_network_rule(config.api.port, update))
    extra = f" {rule.country or rule.uplink}" if rule.country or rule.uplink else ""
    typer.echo(f"{rule.network}: via {rule.via}{extra}, applied")


@net_app.command("rm")
def net_rm(
    network: Annotated[str, typer.Argument(help="The network whose rule goes.")],
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """Remove the rule of a network: in routing.mode smart its addresses go direct again."""
    config = _lan_box(box_dir)
    _core_call(lambda: core_api.remove_network_rule(config.api.port, network))
    typer.echo(f"{network}: rule removed, goes direct in smart")


@rule_app.command("list")
def rule_list(box_dir: BoxDir = DEFAULT_BOX_DIR) -> None:
    """The domain rules of routing.mode smart: each site with its channel."""
    config = _lan_box(box_dir)
    rules = _core_call(lambda: core_api.list_rules(config.api.port))
    if not rules:
        typer.echo("no domain rules (vibedpn rule add <domain> vps|dpn|tor|direct)")
    for rule in rules:
        country = f" {rule.country}" if rule.country else ""
        extras = []
        if not rule.learn:
            extras.append("learn off")
        if rule.also:
            extras.append("also " + ", ".join(rule.also))
        suffix = f"  ({'; '.join(extras)})" if extras else ""
        typer.echo(f"{rule.domain}  {rule.via}{country}{suffix}")


@rule_app.command("add")
def rule_add(
    domain: Annotated[str, typer.Argument(help="The site; its subdomains follow it.")],
    via: Annotated[DomainVia, typer.Argument(help="vps | dpn | wg | tor | direct.")],
    country: Annotated[
        str | None, typer.Option("--country", help="Exit country of via dpn (ISO code).")
    ] = None,
    uplink: Annotated[
        str | None, typer.Option("--uplink", help="The exit of via wg: a name of upstreams.wg.")
    ] = None,
    learn: Annotated[
        bool, typer.Option("--learn/--no-learn", help="CDNs the site calls follow it.")
    ] = True,
    also: Annotated[
        list[str] | None, typer.Option("--also", help="A CDN pinned to the site; repeatable.")
    ] = None,
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """Give a site its channel in routing.mode smart; a rule for the same domain is replaced."""
    config = _lan_box(box_dir)
    update = DomainRuleUpdate(
        via=via.value, country=country, uplink=uplink, learn=learn, also=also or []
    )
    rule = _core_call(lambda: core_api.set_rule(config.api.port, domain, update))
    country_text = f" {rule.country or rule.uplink}" if rule.country or rule.uplink else ""
    typer.echo(f"{rule.domain}: via {rule.via}{country_text}, applied")


@rule_app.command("rm")
def rule_rm(
    domain: Annotated[str, typer.Argument(help="The site whose rule goes.")],
    box_dir: BoxDir = DEFAULT_BOX_DIR,
) -> None:
    """Remove the rule of a site: in routing.mode smart it goes direct again."""
    config = _lan_box(box_dir)
    _core_call(lambda: core_api.remove_rule(config.api.port, domain))
    typer.echo(f"{domain}: rule removed, goes direct in smart")


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
    policy: Annotated[DevicePolicy, typer.Argument(help="vps | dpn | tor | bypass | block.")],
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
