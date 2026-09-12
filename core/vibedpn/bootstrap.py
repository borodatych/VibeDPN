"""Assemble the box configuration from wizard answers and host facts, and write it to disk.

Pure parts (``build_config``, ``render_config``, ``render_env``) are unit-tested without a host;
``write_box`` is the only function that touches the filesystem.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import bcrypt
from jinja2 import Environment, PackageLoader, StrictUndefined

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
    parse_yaml,
)
from vibedpn.detect import Interface

DEFAULT_BOX_DIR = Path("/opt/vibedpn")
DEFAULT_IMAGE_TAG = "latest"
IMAGE_TAG_VAR = "VIBEDPN_TAG"
UI_USER = "admin"
CONFIG_FILE = "config.yaml"
CONFIG_BACKUP = "config.yaml.bak"
ENV_FILE = ".env"
SECRETS_DIR = "secrets"
HTPASSWD_FILE = "htpasswd"
WG_CLIENT_CONF = "wg-client.conf"
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


def public_address(facts: HostFacts) -> str | None:
    """The detected interface address when it is globally routable, else ``None``."""
    if facts.interface is not None and facts.interface.address.is_global:
        return str(facts.interface.address)
    return None


def build_config(answers: Answers, facts: HostFacts) -> Config:
    """A complete role-appropriate configuration; routing starts in ``off`` on every role."""
    if answers.role is Role.VPS:
        endpoint = answers.endpoint or public_address(facts)
        if endpoint is None:
            raise BootstrapError(
                "the public address of this VPS could not be detected;"
                " pass --endpoint <host or IPv4>"
            )
        return Config(
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
        return Config(
            version=1,
            role=Role.HOME,
            network=network,
            routing=RoutingConfig(default_upstream=Upstream.DPN),
            upstreams=UpstreamsConfig(dpn=DpnUplink(enabled=True)),
            provider=ProviderConfig(enabled=True),
        )
    return Config(
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


def render_env(config: Config, image_tag: str) -> str:
    lines = [
        "# VibeDPN — written by `vibedpn init` from config.yaml."
        " Edit config.yaml, then `vibedpn restart`.",
        "",
        *(f"{key}={value}" for key, value in config.env_vars().items()),
        "",
        "# Image tag of ghcr.io/borodatych/vibedpn-{core,wg,ui}; `vibedpn update` moves it.",
        f"{IMAGE_TAG_VAR}={image_tag}",
        "",
    ]
    return "\n".join(lines)


def image_tag_of(env_path: Path) -> str:
    """Keep the tag of an existing ``.env`` across re-runs of ``init``."""
    if not env_path.is_file():
        return DEFAULT_IMAGE_TAG
    for line in env_path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == IMAGE_TAG_VAR and value.strip():
            return value.strip()
    return DEFAULT_IMAGE_TAG


def htpasswd_line(user: str, password: str) -> str:
    """One ``user:hash`` line with a bcrypt hash, as nginx ``auth_basic`` reads it."""
    digest = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
    return f"{user}:{digest}\n"


def write_box(box_dir: Path, config: Config, answers: Answers, *, force: bool) -> list[Path]:
    """Write ``config.yaml``, ``.env`` and ``secrets/``; return the written paths."""
    box_dir.mkdir(parents=True, exist_ok=True)
    config_path = box_dir / CONFIG_FILE
    if config_path.exists():
        if not force:
            raise BootstrapError(
                f"{config_path} exists; re-run with --force to replace it"
                f" (the old file is kept as {CONFIG_BACKUP})"
            )
        shutil.copy2(config_path, box_dir / CONFIG_BACKUP)
    text = render_config(config)
    if Config.model_validate(parse_yaml(text)) != config:
        raise BootstrapError("rendered config.yaml does not round-trip; this is a template bug")
    written = [_write(config_path, text, PUBLIC_FILE_MODE)]
    env_path = box_dir / ENV_FILE
    written.append(_write(env_path, render_env(config, image_tag_of(env_path)), PUBLIC_FILE_MODE))
    secrets = box_dir / SECRETS_DIR
    secrets.mkdir(mode=SECRET_DIR_MODE, exist_ok=True)
    secrets.chmod(SECRET_DIR_MODE)
    if answers.password is not None:
        line = htpasswd_line(UI_USER, answers.password)
        written.append(_write(secrets / HTPASSWD_FILE, line, SECRET_FILE_MODE))
    if answers.peer_config is not None:
        try:
            peer = answers.peer_config.read_text(encoding="utf-8")
        except OSError as exc:
            raise BootstrapError(f"cannot read {answers.peer_config}: {exc.strerror}") from exc
        written.append(_write(secrets / WG_CLIENT_CONF, peer, SECRET_FILE_MODE))
    return written


def _write(path: Path, text: str, mode: int) -> Path:
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)
    return path
