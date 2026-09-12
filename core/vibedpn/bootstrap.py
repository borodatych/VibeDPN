"""Assemble the box configuration from wizard answers and host facts, and write it to disk.

Pure parts (``build_config``, ``render_config``, ``render_env``, ``check_password``) are
unit-tested without a host; ``write_box`` is the only function that touches the filesystem, and
it gathers every byte it will write before creating a single file.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import bcrypt
from jinja2 import Environment, PackageLoader, StrictUndefined
from pydantic import ValidationError

from vibedpn.config import (
    Config,
    DpnUplink,
    NetworkConfig,
    ProviderConfig,
    Role,
    RoutingConfig,
    Upstream,
    UpstreamsConfig,
    VpsUplink,
    WgServerConfig,
    check_endpoint,
    parse_yaml,
)
from vibedpn.detect import Interface

DEFAULT_BOX_DIR = Path("/opt/vibedpn")  # install.sh has the same default; keep them equal
DEFAULT_IMAGE_TAG = "latest"  # what CI publishes from main
RELEASE_BRANCH = "main"
IMAGE_TAG_VAR = "VIBEDPN_TAG"
# docker/metadata-action turns a branch name into a tag by replacing anything else with '-'.
TAG_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")
# Lines of an existing .env that survive a re-run of init: the image tag and the two optional
# overrides of third-party image pins that .env.example documents.
PRESERVED_ENV_VARS = (IMAGE_TAG_VAR, "MYST_TAG", "ADGUARD_TAG")
UI_USER = "admin"
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72  # bcrypt hashes at most 72 bytes; nginx's crypt() has the same limit
MAX_PEER_FILE_BYTES = 64 * 1024
CONFIG_FILE = "config.yaml"
CONFIG_BACKUP = "config.yaml.bak"
ENV_FILE = ".env"
SECRETS_DIR = "secrets"
HTPASSWD_FILE = "htpasswd"
WG_CLIENT_CONF = "wg-client.conf"
KNOWN_SECRETS = (HTPASSWD_FILE, WG_CLIENT_CONF)
BACKUP_SUFFIX = ".bak"
SECRET_DIR_MODE = 0o700
SECRET_FILE_MODE = 0o600
PUBLIC_FILE_MODE = 0o644
CONFIG_TEMPLATE = "config.yaml.j2"


class BootstrapError(ValueError):
    """A user-facing reason why the box cannot be configured."""


@dataclass(frozen=True)
class Answers:
    """What the wizard asked (or received as flags)."""

    role: Role
    password: str | None = None
    peer_config: Path | None = None
    endpoint: str | None = None


@dataclass(frozen=True)
class HostFacts:
    """What the wizard detected."""

    interface: Interface | None
    wireguard_module: bool


@dataclass(frozen=True)
class Written:
    """What ``write_box`` did: files written, and secrets of a previous role set aside."""

    files: list[Path] = field(default_factory=list)
    retired: list[Path] = field(default_factory=list)


def public_address(facts: HostFacts) -> str | None:
    """The detected interface address when it is globally routable, else ``None``."""
    if facts.interface is not None and facts.interface.address.is_global:
        return str(facts.interface.address)
    return None


def check_password(password: str) -> None:
    """Raise ``BootstrapError`` unless the password fits both the policy and bcrypt."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise BootstrapError(f"the password must be at least {MIN_PASSWORD_LENGTH} characters long")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise BootstrapError(
            f"the password must be at most {MAX_PASSWORD_BYTES} bytes in UTF-8 (bcrypt limit);"
            " non-Latin letters take 2 bytes each"
        )


def ensure_replaceable(box_dir: Path, *, force: bool) -> None:
    """Refuse to touch an existing ``config.yaml`` unless ``--force`` was given."""
    if (box_dir / CONFIG_FILE).exists() and not force:
        raise BootstrapError(
            f"{box_dir / CONFIG_FILE} exists; re-run with --force to replace it"
            f" (the old file is kept as {CONFIG_BACKUP})"
        )


def _validated(**fields: object) -> Config:
    try:
        return Config(**fields)  # type: ignore[arg-type]
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise BootstrapError(problems) from None


def build_config(answers: Answers, facts: HostFacts) -> Config:
    """A complete role-appropriate configuration; routing starts in ``off`` on every role."""
    if answers.role is Role.VPS:
        endpoint = answers.endpoint or public_address(facts)
        if endpoint is None:
            raise BootstrapError(
                "the public address of this VPS could not be detected;"
                " pass --endpoint <host or IPv4>"
            )
        try:
            check_endpoint(endpoint)
        except ValueError as exc:
            raise BootstrapError(f"endpoint: {exc}; give the host without a port") from None
        return _validated(
            version=1,
            role=Role.VPS,
            provider=ProviderConfig(enabled=True),
            wg_server=WgServerConfig(endpoint=endpoint),
        )
    if facts.interface is None:
        raise BootstrapError(
            "no interface with a default route was found; connect the box to the LAN first"
        )
    network = NetworkConfig(
        lan_interface=facts.interface.name,
        lan_subnet=facts.interface.subnet,
        lan_address=facts.interface.address,
    )
    if answers.role is Role.HOME:
        return _validated(
            version=1,
            role=Role.HOME,
            network=network,
            routing=RoutingConfig(default_upstream=Upstream.DPN),
            upstreams=UpstreamsConfig(dpn=DpnUplink(enabled=True)),
            provider=ProviderConfig(enabled=True),
        )
    return _validated(
        version=1,
        role=Role.CLIENT,
        network=network,
        routing=RoutingConfig(default_upstream=Upstream.VPS),
        upstreams=UpstreamsConfig(vps=VpsUplink(enabled=True)),
    )


def render_config(config: Config) -> str:
    """``config.yaml`` text with the same comments a hand-written file would carry."""
    environment = Environment(
        loader=PackageLoader("vibedpn", "templates"),
        undefined=StrictUndefined,
        autoescape=False,  # YAML, not HTML
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    template = environment.get_template(CONFIG_TEMPLATE)
    return template.render(config=config, lan=config.role is not Role.VPS)


def checkout_image_tag(box_dir: Path) -> str:
    """The image tag CI publishes for the checked-out branch: ``latest`` for main, else the branch.

    A box installed with ``VIBEDPN_BRANCH=next`` must pull ``:next``; ``:latest`` does not exist
    until the first release, and Compose would silently build the images locally instead.
    """
    try:
        probe = subprocess.run(
            ["git", "-C", str(box_dir), "symbolic-ref", "--short", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return DEFAULT_IMAGE_TAG
    branch = probe.stdout.strip()
    if probe.returncode != 0 or not branch or branch == RELEASE_BRANCH:
        return DEFAULT_IMAGE_TAG
    return TAG_UNSAFE.sub("-", branch)


def preserved_env(env_path: Path, default_tag: str = DEFAULT_IMAGE_TAG) -> dict[str, str]:
    """Values of an existing ``.env`` that a re-run keeps; the image tag always has a value."""
    kept = {IMAGE_TAG_VAR: default_tag}
    if not env_path.is_file():
        return kept
    for line in env_path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() in PRESERVED_ENV_VARS and value.strip():
            kept[key.strip()] = value.strip()
    return kept


def render_env(config: Config, preserved: dict[str, str]) -> str:
    lines = [
        "# VibeDPN — written by `vibedpn init` from config.yaml."
        " Edit config.yaml, then `vibedpn restart`.",
        "",
        *(f"{key}={value}" for key, value in config.env_vars().items()),
        "",
        "# Image tag of ghcr.io/borodatych/vibedpn-{core,wg,ui}; `vibedpn update` moves it."
        " MYST_TAG / ADGUARD_TAG override the pins in compose.yaml.",
        *(f"{key}={preserved[key]}" for key in PRESERVED_ENV_VARS if key in preserved),
        "",
    ]
    return "\n".join(lines)


def htpasswd_line(user: str, password: str) -> str:
    """One ``user:hash`` line with a bcrypt hash, as nginx ``auth_basic`` reads it."""
    check_password(password)
    digest = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
    return f"{user}:{digest}\n"


def read_peer_config(path: Path) -> str:
    """The WireGuard peer file as text, or a ``BootstrapError`` saying what is wrong with it."""
    try:
        if path.stat().st_size > MAX_PEER_FILE_BYTES:
            raise BootstrapError(f"{path} is larger than a WireGuard peer file can be")
        text = path.read_bytes().decode("utf-8")
    except OSError as exc:
        raise BootstrapError(f"cannot read {path}: {exc.strerror}") from exc
    except UnicodeDecodeError:
        raise BootstrapError(
            f"{path} is not a UTF-8 text file (expected a WireGuard .conf)"
        ) from None
    if "[Interface]" not in text:
        raise BootstrapError(f"{path} has no [Interface] section; is it a WireGuard .conf?")
    return text


def write_box(box_dir: Path, config: Config, answers: Answers, *, force: bool) -> Written:
    """Write ``config.yaml``, ``.env`` and ``secrets/``.

    Everything is rendered, hashed and read before the first file is created, so a bad input
    never leaves a half-configured directory behind.
    """
    ensure_replaceable(box_dir, force=force)
    config_path = box_dir / CONFIG_FILE
    env_path = box_dir / ENV_FILE
    secrets_dir = box_dir / SECRETS_DIR
    text = render_config(config)
    if Config.model_validate(parse_yaml(text)) != config:
        raise BootstrapError("rendered config.yaml does not round-trip; this is a template bug")
    env_text = render_env(config, preserved_env(env_path, checkout_image_tag(box_dir)))
    secrets: dict[str, str] = {}
    if answers.password is not None:
        secrets[HTPASSWD_FILE] = htpasswd_line(UI_USER, answers.password)
    if answers.peer_config is not None:
        secrets[WG_CLIENT_CONF] = read_peer_config(answers.peer_config)
    result = Written()
    try:
        box_dir.mkdir(parents=True, exist_ok=True)
        if config_path.exists():
            shutil.copy2(config_path, box_dir / CONFIG_BACKUP)
        result.files.append(write_file(config_path, text, PUBLIC_FILE_MODE))
        result.files.append(write_file(env_path, env_text, PUBLIC_FILE_MODE))
        # The top-level files belong to the person, not to root: `vibedpn up` rewrites .env and
        # later commands edit config.yaml without sudo. secrets/ stays root-only.
        for path in (config_path, env_path, box_dir / CONFIG_BACKUP):
            if path.exists():
                give_to_invoker(path)
        secrets_dir.mkdir(mode=SECRET_DIR_MODE, exist_ok=True)
        secrets_dir.chmod(SECRET_DIR_MODE)
        for name, content in secrets.items():
            result.files.append(write_file(secrets_dir / name, content, SECRET_FILE_MODE))
        for name in KNOWN_SECRETS:
            stale = secrets_dir / name
            if name not in secrets and stale.exists():
                retired = stale.with_name(name + BACKUP_SUFFIX)
                stale.replace(retired)
                retired.chmod(SECRET_FILE_MODE)
                result.retired.append(retired)
    except OSError as exc:
        target = exc.filename or box_dir
        raise BootstrapError(f"cannot write {target}: {exc.strerror}; run with sudo?") from exc
    return result


def invoker_ids() -> tuple[int, int] | None:
    """uid/gid of the person behind ``sudo``, when running as root through sudo."""
    if os.geteuid() != 0:
        return None
    uid, gid = os.environ.get("SUDO_UID"), os.environ.get("SUDO_GID")
    if uid is None or gid is None or not uid.isdigit() or not gid.isdigit():
        return None
    return int(uid), int(gid)


def give_to_invoker(path: Path) -> None:
    """Hand a file written under sudo back to the invoking user (no-op otherwise)."""
    ids = invoker_ids()
    if ids is not None:
        os.chown(path, *ids)


def write_file(path: Path, text: str, mode: int) -> Path:
    """Write text creating the file with ``mode`` so a secret is never readable via the umask."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
    path.chmod(mode)
    return path
