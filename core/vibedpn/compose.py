"""Docker Compose over the box directory.

Pure parts (argv building, precondition checks, ``ps`` parsing) are unit-tested; ``run`` and
``preflight`` are the only functions that execute anything.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from vibedpn.bootstrap import (
    CONFIG_FILE,
    ENV_FILE,
    PUBLIC_FILE_MODE,
    SECRET_FILE_MODE,
    SECRETS_DIR,
    WG_CLIENT_CONF,
    XRAY_LINK_FILE,
    checkout_image_tag,
    give_to_invoker,
    preserved_env,
    read_env,
    render_env,
    required_secrets,
    secrets_present,
    wg_uplink_file,
    write_file,
)
from vibedpn.config import DIGEST_LENGTH, Config, ConfigError, Profile, Role, load_config
from vibedpn.engine.router import country_uplinks, wg_uplinks
from vibedpn.engine.xray import XRAY_UID, XrayError, config_from_link

COMPOSE_FILE = "compose.yaml"
COUNTRIES_FILE = "compose.countries.yaml"
WG_UPLINKS_FILE = "compose.wg.yaml"
OVERRIDE_FILE = "compose.override.yaml"
# The bridges of uplink tor for its gateway: a directory is mounted, not the file, so that rewriting
# the file never meets EBUSY of a file bind-mount (knowledge docker/bindMountRename.md).
TOR_CONFIG_DIR = "data/tor/config"
TOR_BRIDGES_FILE = "bridges"
# The rendered configuration of uplink xray, for the same reason in a directory of its own. It
# carries the credentials of the share link, so it is written with the mode of a secret.
XRAY_CONFIG_DIR = "data/xray/config"
XRAY_CONFIG_FILE = "config.json"
# Fingerprints in .env of the files a gateway reads at start that config.yaml does not describe:
# the configuration rendered from the share link of uplink xray, and the WireGuard peer files.
# Compose recreates a service only when its definition changes, and a peer file is bind-mounted on
# its own, so a new one written by rename never reaches the running container (knowledge
# docker/bindMountRename.md).
DIGEST_XRAY = "VIBEDPN_DIGEST_XRAY"
DIGEST_WG_CLIENT = "VIBEDPN_DIGEST_WG_CLIENT"
# not VIBEDPN_DIGEST_WG_<NAME>: an exit named `server` would take the fingerprint of wg-server
WG_UPLINK_DIGEST_PREFIX = "VIBEDPN_DIGEST_WG_UPLINK_"
DEFAULT_LOG_TAIL = 100
# the images this host keeps, named the way `compose config` names them
IMAGE_LISTING = ["docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}"]
# Before 28.0.0 ports published on 127.0.0.1 were reachable from L2 neighbours (Docker release
# notes 28.0.0), and nat-unprotected did not exist; the box relies on both.
MIN_DOCKER_ENGINE = (28, 0, 0)
ENGINE_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")


class ComposeError(RuntimeError):
    """A user-facing reason why Compose cannot be driven, with the command that fixes it."""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(f"{message}; {hint}" if hint else message)
        self.message = message
        self.hint = hint


@dataclass(frozen=True)
class ServiceStatus:
    service: str
    state: str
    health: str
    status: str


def compose_files(box_dir: Path) -> list[Path]:
    """compose.yaml, the generated consumers of the exit countries, and the owner's own
    compose.override.yaml: with explicit ``-f`` Compose reads nothing else (knowledge
    compose/hostNetworkAndProfiles.md), so an existing override must be named too."""
    files = [box_dir / COMPOSE_FILE]
    files += [
        path
        for path in (box_dir / COUNTRIES_FILE, box_dir / WG_UPLINKS_FILE, box_dir / OVERRIDE_FILE)
        if path.is_file()
    ]
    return files


def compose_argv(box_dir: Path, *args: str, all_profiles: bool = False) -> list[str]:
    """``docker compose`` invocation rooted at the box directory (``.env`` is read from there)."""
    argv = ["docker", "compose", "--project-directory", str(box_dir)]
    for path in compose_files(box_dir):
        argv += ["-f", str(path)]
    if all_profiles:
        argv += ["--profile", "*"]
    return argv + list(args)


def check_box(box_dir: Path) -> Config:
    """The box directory must be a checkout with a valid ``config.yaml``."""
    if not (box_dir / COMPOSE_FILE).is_file():
        raise ComposeError(
            f"{box_dir} is not a VibeDPN checkout (no {COMPOSE_FILE})", "run install.sh"
        )
    if not (box_dir / CONFIG_FILE).is_file():
        raise ComposeError(f"no {CONFIG_FILE} in {box_dir}", "run `vibedpn init` first")
    try:
        return load_config(box_dir / CONFIG_FILE)
    except (ConfigError, ValidationError) as exc:
        raise ComposeError(
            f"{CONFIG_FILE} is invalid: {exc}",
            f"fix that key in {CONFIG_FILE} (docs/manuals/configSpec.md)",
        ) from None


def check_secrets(box_dir: Path, config: Config) -> None:
    """Refuse to start a box whose secrets are missing: the node would fall back to its public
    default password. A secret that cannot be stat-ed (root-only dir, not root) is not a failure."""
    needed = required_secrets(config)
    present = secrets_present(box_dir, needed)
    missing = [name for name in needed if present.get(name) is False]
    if missing:
        raise ComposeError(
            f"missing {', '.join(missing)}", "run `sudo vibedpn init --force` to create it"
        )


def engine_too_old(version: str) -> bool:
    """``True`` for a parseable Engine version below the floor; unknown strings never block."""
    match = ENGINE_VERSION.match(version.strip())
    if match is None:
        return False
    return tuple(int(part) for part in match.groups()) < MIN_DOCKER_ENGINE


def wg_uplink_digest(name: str) -> str:
    """The .env variable of a named exit's peer file; WG_UPLINK_NAME has no '_', so none collide."""
    return WG_UPLINK_DIGEST_PREFIX + name.upper().replace("-", "_")


def file_digest(path: Path) -> str | None:
    """The fingerprint of a file's bytes: empty when there is no file, ``None`` when this user
    cannot read it — a secret, and `vibedpn up` without sudo."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:DIGEST_LENGTH]
    except FileNotFoundError:
        return ""
    except PermissionError:
        return None


def file_digests(box_dir: Path, config: Config) -> dict[str, str | None]:
    """The files the gateways this configuration runs read at start, by their .env variable."""
    files: dict[str, Path] = {}
    if config.upstreams.xray.enabled:
        files[DIGEST_XRAY] = box_dir / XRAY_CONFIG_DIR / XRAY_CONFIG_FILE
    if config.role is Role.CLIENT:
        files[DIGEST_WG_CLIENT] = box_dir / SECRETS_DIR / WG_CLIENT_CONF
    for name, uplink in sorted(config.upstreams.wg.items()):
        if uplink.enabled:
            files[wg_uplink_digest(name)] = box_dir / SECRETS_DIR / wg_uplink_file(name)
    return {variable: file_digest(path) for variable, path in files.items()}


def settled_digests(current: dict[str, str | None], previous: dict[str, str]) -> dict[str, str]:
    """The fingerprints .env keeps: a file this user cannot read keeps the one it had, because
    `up` without sudo cannot tell whether it changed — the sudo commands that replace such a file
    refresh .env themselves."""
    return {
        variable: digest if digest is not None else previous.get(variable, "")
        for variable, digest in current.items()
    }


def refresh_env(box_dir: Path, config: Config) -> Path:
    """Re-derive ``.env`` from ``config.yaml`` so hand edits to the config take effect, together
    with the fingerprints of the files the gateways read at start."""
    env_path = box_dir / ENV_FILE
    preserved = preserved_env(env_path, checkout_image_tag(box_dir))
    files = settled_digests(file_digests(box_dir, config), read_env(env_path))
    try:
        write_file(env_path, render_env(config, preserved, files), PUBLIC_FILE_MODE)
        give_to_invoker(env_path)
    except OSError as exc:
        raise ComposeError(f"cannot write {env_path}: {exc.strerror}; run with sudo?") from exc
    return env_path


def render_countries(config: Config) -> str:
    """One consumer per exit country of routing rules and lists, extending `myst-consumer` of
    compose.yaml:
    only its address in the gateway network and its data directory differ (decision 20)."""
    lines = [
        "# Generated by vibedpn from routing rules and lists at every `up`/`restart`; do not edit.",
        "# One Mysterium consumer per exit country (docs/decisions.md, 20).",
    ]
    uplinks = country_uplinks(config)
    if not uplinks:
        return "\n".join([*lines, "services: {}"]) + "\n"
    lines.append("services:")
    for country, uplink in uplinks.items():
        code = country.lower()
        lines += [
            f"  myst-consumer-{code}:",
            "    extends:",
            f"      file: {COMPOSE_FILE}",
            "      service: myst-consumer",
            "    networks:",
            "      upstreams:",
            f"        ipv4_address: {uplink.gateway}",
            "    volumes:",
            f"      - ./data/myst-consumer-{code}:/var/lib/mysterium-node",
        ]
    return "\n".join(lines) + "\n"


def refresh_countries(box_dir: Path, config: Config) -> Path:
    """Write compose.countries.yaml; it exists on every box, with no services when no rule asks
    for a country."""
    path = box_dir / COUNTRIES_FILE
    try:
        write_file(path, render_countries(config), PUBLIC_FILE_MODE)
        give_to_invoker(path)
    except OSError as exc:
        raise ComposeError(f"cannot write {path}: {exc.strerror}; run with sudo?") from exc
    return path


def render_wg_uplinks(config: Config) -> str:
    """One gateway per named WireGuard exit, extending `wg-client` of compose.yaml: only its
    address in the gateway network, its peer file and its profile differ (decision 23).

    The profile matters: `extends` adds to the profiles of the base service instead of replacing
    them, so these services carry `wg-client` as well. Only `wg-uplink` is active on a box that
    has no `secrets/wg-client.conf`, which keeps the base service out while these start.
    """
    lines = [
        "# Generated by vibedpn from upstreams.wg at every `up`/`restart`; do not edit.",
        "# One WireGuard gateway per named exit (docs/decisions.md, 23).",
    ]
    # A disabled exit keeps its settings and its number (marks of the others do not move), but gets
    # no container: without its file it would stop the whole `up`.
    uplinks = {
        name: uplink
        for name, uplink in wg_uplinks(config).items()
        if config.upstreams.wg[name].enabled
    }
    if not uplinks:
        return "\n".join([*lines, "services: {}"]) + "\n"
    lines.append("services:")
    for name, uplink in uplinks.items():
        lines += [
            f"  wg-{name}:",
            "    extends:",
            f"      file: {COMPOSE_FILE}",
            "      service: wg-client",
            "    profiles:",
            f"      - {Profile.WG_UPLINK.value}",
            # the fingerprint of its own peer file in place of the one of wg-client (file_digests)
            "    environment:",
            f"      VIBEDPN_CONFIG_DIGEST: ${{{wg_uplink_digest(name)}:-}}",
            "    networks:",
            "      upstreams:",
            f"        ipv4_address: {uplink.gateway}",
            "    volumes:",
            # The same target as the base service, so this mount replaces it rather than adding one
            "      - type: bind",
            f"        source: ./{SECRETS_DIR}/{wg_uplink_file(name)}",
            "        target: /etc/wireguard/wg0.conf",
            "        read_only: true",
            "        bind:",
            "          create_host_path: false",
        ]
    return "\n".join(lines) + "\n"


def refresh_wg_uplinks(box_dir: Path, config: Config) -> Path:
    """Write compose.wg.yaml; it exists on every box, with no services when no name is set."""
    path = box_dir / WG_UPLINKS_FILE
    try:
        write_file(path, render_wg_uplinks(config), PUBLIC_FILE_MODE)
        give_to_invoker(path)
    except OSError as exc:
        raise ComposeError(f"cannot write {path}: {exc.strerror}; run with sudo?") from exc
    return path


def render_tor_bridges(config: Config) -> str:
    """The bridge lines of upstreams.tor, one per line, as images/tor/entrypoint.sh reads them."""
    header = "# Written by vibedpn from upstreams.tor.bridges of config.yaml; edit that instead.\n"
    return header + "".join(f"{line}\n" for line in config.upstreams.tor.bridges)


def refresh_tor_bridges(box_dir: Path, config: Config) -> Path:
    """Write data/tor/config/bridges; on every box, so enabling uplink tor needs no second step."""
    directory = box_dir / TOR_CONFIG_DIR
    path = directory / TOR_BRIDGES_FILE
    try:
        directory.mkdir(parents=True, exist_ok=True)
        write_file(path, render_tor_bridges(config), PUBLIC_FILE_MODE)
    except OSError as exc:
        raise ComposeError(f"cannot write {path}: {exc.strerror}; run with sudo?") from exc
    return path


def refresh_xray_config(box_dir: Path, config: Config) -> Path | None:
    """Render data/xray/config/config.json from the share link in ``secrets/``; ``None`` when this
    box has no uplink xray or no link yet — the missing secret is what `doctor` reports, and a
    half-written configuration would start a gateway that leads nowhere."""
    if not config.upstreams.xray.enabled:
        return None
    link_path = box_dir / SECRETS_DIR / XRAY_LINK_FILE
    try:
        link = link_path.read_text(encoding="utf-8")
    except OSError:
        return None
    directory = box_dir / XRAY_CONFIG_DIR
    path = directory / XRAY_CONFIG_FILE
    try:
        rendered = config_from_link(link)
    except XrayError as exc:
        raise ComposeError(f"{link_path}: {exc}") from None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        write_file(path, rendered, SECRET_FILE_MODE)
        # The gateway does not run as root, and the file keeps the mode of a secret: so it changes
        # owner instead of mode, or xray cannot read what core just wrote for it.
        os.chown(path, XRAY_UID, XRAY_UID)
    except OSError as exc:
        raise ComposeError(f"cannot write {path}: {exc.strerror}; run with sudo?") from exc
    return path


def stale_services(all_services: str, active_services: str) -> list[str]:
    """Services of profiles that are no longer active (``config --services`` with and without
    ``--profile '*'``). ``up --remove-orphans`` leaves their containers alone: Compose treats a
    disabled service as known, not as an orphan."""
    active = {line.strip() for line in active_services.splitlines() if line.strip()}
    every = {line.strip() for line in all_services.splitlines() if line.strip()}
    return sorted(every - active)


def kept_services(config_json: str, image_listing: str, services: list[str]) -> list[str]:
    """Those of ``services`` whose image this host keeps already. Compose pulls a missing image
    when a service first starts but runs a kept one as it is, and ``compose pull`` refreshes only
    the active profiles: a service enabled after an update would start on a copy pulled long before
    under the same moving tag, older than the code around it.

    ``config_json`` is ``compose config --format json``; ``image_listing`` is ``docker image ls``
    as ``repository:tag`` lines (IMAGE_LISTING).
    """
    kept = {line.strip() for line in image_listing.splitlines() if line.strip()}
    specs = json.loads(config_json).get("services", {})
    return [service for service in services if specs.get(service, {}).get("image") in kept]


def parse_ps(output: str) -> list[ServiceStatus]:
    """``docker compose ps --format json``: one JSON object per line, or one JSON array."""
    text = output.strip()
    if not text:
        return []
    try:
        loaded = json.loads(text)
        records = loaded if isinstance(loaded, list) else [loaded]
    except json.JSONDecodeError:
        try:
            records = [json.loads(line) for line in text.splitlines() if line.strip()]
        except json.JSONDecodeError:
            raise ComposeError(f"unexpected `docker compose ps` output: {text[:200]!r}") from None
    if not all(isinstance(record, dict) for record in records):
        raise ComposeError(f"unexpected `docker compose ps` output: {text[:200]!r}")
    return [
        ServiceStatus(
            service=str(record.get("Service", "?")),
            state=str(record.get("State", "?")),
            health=str(record.get("Health", "") or "-"),
            status=str(record.get("Status", "")),
        )
        for record in records
    ]


def preflight() -> None:
    """One readable error instead of Docker's own when the CLI or the daemon is unreachable."""
    try:
        probe = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ComposeError("docker not found; run install.sh") from exc
    if probe.returncode == 0:
        version = probe.stdout.strip()
        if engine_too_old(version):
            floor = ".".join(str(part) for part in MIN_DOCKER_ENGINE)
            raise ComposeError(
                f"Docker Engine {version} is older than {floor}: ports published on 127.0.0.1"
                " are reachable from the LAN on such versions",
                "remove the distro Docker (apt-get purge docker.io docker-compose) and re-run"
                " install.sh to get docker-ce from download.docker.com",
            )
        return
    # Match the dial error, which is the same across CLI versions, not the surrounding prose
    # (Docker 29 says "failed to connect to the docker API", older ones "Cannot connect").
    stderr = probe.stderr.strip().lower()
    if "permission denied" in stderr:
        raise ComposeError(
            "no access to the Docker socket: log out and in again after install.sh added you"
            " to the docker group, or run with sudo"
        )
    if "no such file or directory" in stderr or "connection refused" in stderr:
        raise ComposeError("the Docker daemon is not running: sudo systemctl start docker")
    raise ComposeError(f"docker is not usable: {probe.stderr.strip()}")


def run(argv: list[str]) -> int:
    """Run Compose with inherited stdio so the user sees its output live; return its exit code."""
    try:
        return subprocess.run(argv, check=False).returncode
    except FileNotFoundError as exc:
        raise ComposeError("docker not found; run install.sh") from exc


def capture(argv: list[str]) -> str:
    """Run Compose and return stdout; a failure becomes a ``ComposeError`` with its stderr."""
    try:
        completed = subprocess.run(argv, check=False, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise ComposeError("docker not found; run install.sh") from exc
    if completed.returncode != 0:
        raise ComposeError(
            completed.stderr.strip() or f"docker compose exited {completed.returncode}"
        )
    return completed.stdout
