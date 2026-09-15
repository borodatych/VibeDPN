"""Assemble the box configuration from wizard answers and host facts, and write it to disk.

Pure parts (``build_config``, ``render_config``, ``render_env``, ``check_password``) are
unit-tested without a host; ``write_box`` is the only function that touches the filesystem, and
it gathers every byte it will write before creating a single file.
"""

from __future__ import annotations

import os
import re
import secrets as secrets_module
import shutil
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import bcrypt
from pydantic import ValidationError

from vibedpn.config import (
    Config,
    DhcpConfig,
    DpnUplink,
    FirewallConfig,
    NetworkConfig,
    NetworkMode,
    Profile,
    ProviderConfig,
    Role,
    RoutingConfig,
    UiConfig,
    UiVariant,
    Upstream,
    UpstreamsConfig,
    VpsUplink,
    WgServerConfig,
    WifiConfig,
    check_endpoint,
    parse_yaml,
)
from vibedpn.detect import DEFAULT_SSH_PORT, Interface
from vibedpn.engine.hostapd import PASSPHRASE_FILE as WIFI_PASSPHRASE_FILE
from vibedpn.templating import template_environment

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
MAX_PASSWORD_BYTES = 72  # bcrypt hashes at most 72 bytes, whoever verifies the hash
MAX_PEER_FILE_BYTES = 64 * 1024
# Below this much memory init picks the lite panel (docs/uiVariants.md); the owner can override.
LITE_BELOW_MEMORY_BYTES = 4 * 1024**3
CONFIG_FILE = "config.yaml"
CONFIG_BACKUP = "config.yaml.bak"
ENV_FILE = ".env"
SECRETS_DIR = "secrets"
HTPASSWD_FILE = "htpasswd"
WG_CLIENT_CONF = "wg-client.conf"
# The panel's own secrets: generated once and kept by every re-run of init, because the database
# volume (data/ui-db) and the signed sessions depend on them. Written without a trailing newline.
UI_DB_PASSWORD_FILE = "ui-db-password"
UI_AUTH_SECRET_FILE = "ui-auth-secret"
UI_SECRETS = (UI_DB_PASSWORD_FILE, UI_AUTH_SECRET_FILE)
# Core's own AdGuard user (engine/adguard.py): changes the DNS mode live without the owner's
# password.
ADGUARD_CORE_PASSWORD_FILE = "adguard-core-password"
ADGUARD_SECRETS = (ADGUARD_CORE_PASSWORD_FILE,)
# The passphrase of the dpn consumer identity (engine/consumer.py): losing it locks the identity.
MYST_CONSUMER_PASSPHRASE_FILE = "myst-consumer-passphrase"
CONSUMER_SECRETS = (MYST_CONSUMER_PASSPHRASE_FILE,)
# One consumer per exit country of routing rules and lists (docs/decisions.md, 20), each with its
# identity.
COUNTRY_PASSPHRASE_TEMPLATE = "myst-consumer-{country}-passphrase"
# The Wi-Fi passphrase of gateway mode: generated like the others, shown by `vibedpn wifi show`.
WIFI_SECRETS = (WIFI_PASSPHRASE_FILE,)
GENERATED_SECRETS = UI_SECRETS + ADGUARD_SECRETS + CONSUMER_SECRETS + WIFI_SECRETS
GENERATED_SECRET_BYTES = 32
KNOWN_SECRETS = (HTPASSWD_FILE, WG_CLIENT_CONF, *GENERATED_SECRETS)
DATA_DIR = "data"
MYST_PROVIDER_DATA = "myst-provider"  # bind-mounted to /var/lib/mysterium-node in compose.yaml
# The node reads its panel (NodeUI) password from this bcrypt file in its data dir at start;
# without it the node falls back to the public default (myst/mystberry).
NODEUI_PASS_FILE = "nodeui-pass"
NODEUI_USER = "myst"
DATA_DIR_MODE = 0o755
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
    password: str | None = None  # panels: VibeDPN UI/API and the node's NodeUI
    peer_config: Path | None = None
    endpoint: str | None = None
    ui_variant: UiVariant | None = None  # None: chosen by the memory of the host
    # gateway mode: the LAN side, another interface than the default-route one (the WAN)
    lan_interface: str | None = None
    wifi: WifiConfig | None = None  # the access point on that LAN interface


@dataclass(frozen=True)
class HostFacts:
    """What the wizard detected."""

    interface: Interface | None  # the default-route one: the LAN in sidecar, the WAN in gateway
    wireguard_module: bool | None  # None: could not check (no modprobe on PATH)
    ssh_ports: list[int] = field(default_factory=lambda: [DEFAULT_SSH_PORT])
    memory_bytes: int | None = None  # None: /proc/meminfo could not be read
    interfaces: list[Interface] = field(default_factory=list)  # every one with a global IPv4


@dataclass(frozen=True)
class Written:
    """What ``write_box`` did: files written, and secrets of a previous role set aside."""

    files: list[Path] = field(default_factory=list)
    retired: list[Path] = field(default_factory=list)


def required_secrets(config: Config) -> list[str]:
    """Secret files a box of this configuration cannot run without."""
    needed = [HTPASSWD_FILE]
    if config.role is Role.CLIENT:
        needed.append(WG_CLIENT_CONF)
    if config.provider.enabled:
        needed.append(NODEUI_PASS_FILE)
    needed.extend(generated_secrets(config))
    needed.extend(country_secrets(config))
    return needed


def generated_secrets(config: Config) -> tuple[str, ...]:
    """Secrets ``init`` generates itself for this configuration: the panel's when it runs one,
    core's AdGuard user when it runs AdGuard."""
    profiles = config.compose_profiles()
    return (
        (UI_SECRETS if Profile.UI in profiles else ())
        + (ADGUARD_SECRETS if Profile.DNS in profiles else ())
        + (CONSUMER_SECRETS if Profile.CONSUMER in profiles else ())
        + (WIFI_SECRETS if Profile.WIFI in profiles else ())
    )


def _present(path: Path) -> bool | None:
    """``None`` when the file cannot even be stat-ed (root-only directory, not root)."""
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return None


def secrets_present(box_dir: Path, extra: Iterable[str] = ()) -> dict[str, bool | None]:
    """Presence of every known secret, checked one by one so a closed secrets/ does not hide
    the node's password file, which lives in the world-readable data/ tree."""
    found: dict[str, bool | None] = {
        name: _present(box_dir / SECRETS_DIR / name) for name in (*KNOWN_SECRETS, *extra)
    }
    found[NODEUI_PASS_FILE] = _present(box_dir / DATA_DIR / MYST_PROVIDER_DATA / NODEUI_PASS_FILE)
    return found


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


def ui_variant_for(answers: Answers, facts: HostFacts) -> UiVariant:
    """The flag when given; otherwise lite below ``LITE_BELOW_MEMORY_BYTES``, full above it and
    when the memory is unknown."""
    if answers.ui_variant is not None:
        return answers.ui_variant
    if facts.memory_bytes is not None and facts.memory_bytes < LITE_BELOW_MEMORY_BYTES:
        return UiVariant.LITE
    return UiVariant.FULL


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
            firewall=FirewallConfig(ssh_ports=facts.ssh_ports),
        )
    if facts.interface is None:
        raise BootstrapError(
            "no interface with a default route was found; connect the box to the LAN first"
        )
    network = network_for(
        answers.lan_interface, facts.interfaces, facts.interface, wifi=answers.wifi
    )
    if answers.role is Role.HOME:
        return _validated(
            version=1,
            role=Role.HOME,
            network=network,
            ui=UiConfig(variant=ui_variant_for(answers, facts)),
            routing=RoutingConfig(default_upstream=Upstream.DPN),
            upstreams=UpstreamsConfig(dpn=DpnUplink(enabled=True)),
            provider=ProviderConfig(enabled=True),
        )
    return _validated(
        version=1,
        role=Role.CLIENT,
        network=network,
        ui=UiConfig(variant=ui_variant_for(answers, facts)),
        routing=RoutingConfig(default_upstream=Upstream.VPS),
        upstreams=UpstreamsConfig(vps=VpsUplink(enabled=True)),
    )


def network_for(
    lan_interface: str | None,
    interfaces: list[Interface],
    default: Interface,
    *,
    wifi: WifiConfig | None = None,
    dhcp: DhcpConfig | None = None,
) -> NetworkConfig:
    """sidecar on the default-route interface, or gateway: that one is the WAN and the chosen
    interface the LAN, with the static address the OS gave it (docs/decisions.md, decision 7).
    ``wifi`` and ``dhcp`` of an unchanged LAN are carried over; without ``dhcp`` the default pool
    is written out, so the owner sees and edits it in config.yaml."""
    if lan_interface is None or lan_interface == default.name:
        if wifi is not None:
            raise BootstrapError("Wi-Fi needs a LAN interface other than the default-route one")
        return NetworkConfig(
            lan_interface=default.name, lan_subnet=default.subnet, lan_address=default.address
        )
    found = next((i for i in interfaces if i.name == lan_interface), None)
    if found is None:
        others = ", ".join(
            f"{i.name} ({i.address}/{i.prefixlen})" for i in interfaces if i != default
        )
        raise BootstrapError(
            f"LAN interface {lan_interface} has no IPv4 address; give it a static one"
            " first (docs/manuals/installation.md, gateway mode)."
            f" With an address: {others or 'none'}"
        )
    lan: Interface = found

    def gateway(pool: DhcpConfig | None) -> NetworkConfig:
        return NetworkConfig(
            mode=NetworkMode.GATEWAY,
            lan_interface=lan.name,
            lan_subnet=lan.subnet,
            lan_address=lan.address,
            wan_interface=default.name,
            dhcp=pool,
            wifi=wifi,
        )

    try:
        if dhcp is not None:
            return gateway(dhcp)
        start, end = gateway(None).dhcp_pool()
        return gateway(DhcpConfig(range_start=start, range_end=end))
    except ValidationError as exc:
        raise BootstrapError(f"network: {exc.errors()[0]['msg']}") from None


def render_config(config: Config) -> str:
    """``config.yaml`` text with the same comments a hand-written file would carry."""
    template = template_environment().get_template(CONFIG_TEMPLATE)
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


def bcrypt_hash(password: str) -> str:
    """A bcrypt hash of a policy-checked password (``$2b$``; panel, AdGuard and node accept it)."""
    check_password(password)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def htpasswd_line(user: str, password: str) -> str:
    """One ``user:hash`` bcrypt line; the panel reads the ``admin`` line on every sign-in."""
    return f"{user}:{bcrypt_hash(password)}\n"


def set_panel_password(box_dir: Path, config: Config, password: str) -> list[Path]:
    """Replace the panel password: the ``admin`` line of secrets/htpasswd and, on a box with the
    provider node, its NodeUI hash. Both are hashed before either file is touched."""
    line = htpasswd_line(UI_USER, password)
    node_pass = bcrypt_hash(password) + "\n" if config.provider.enabled else None
    written = []
    try:
        written.append(write_file(box_dir / SECRETS_DIR / HTPASSWD_FILE, line, SECRET_FILE_MODE))
        if node_pass is not None:
            path = box_dir / DATA_DIR / MYST_PROVIDER_DATA / NODEUI_PASS_FILE
            path.parent.mkdir(mode=DATA_DIR_MODE, parents=True, exist_ok=True)
            written.append(write_file(path, node_pass, SECRET_FILE_MODE))
    except OSError as exc:
        target = exc.filename or box_dir
        raise BootstrapError(f"cannot write {target}: {exc.strerror}; run with sudo?") from exc
    return written


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
    text = render_config(config)
    if Config.model_validate(parse_yaml(text)) != config:
        raise BootstrapError("rendered config.yaml does not round-trip; this is a template bug")
    env_text = render_env(config, preserved_env(box_dir / ENV_FILE, checkout_image_tag(box_dir)))
    secrets: dict[str, str] = {}
    if answers.password is not None:
        secrets[HTPASSWD_FILE] = htpasswd_line(UI_USER, answers.password)
    if answers.peer_config is not None:
        secrets[WG_CLIENT_CONF] = read_peer_config(answers.peer_config)
    node_pass = None
    if answers.password is not None and config.provider.enabled:
        node_pass = bcrypt_hash(answers.password) + "\n"
    try:
        return _write_files(box_dir, text, env_text, secrets, node_pass, generated_secrets(config))
    except OSError as exc:
        target = exc.filename or box_dir
        raise BootstrapError(f"cannot write {target}: {exc.strerror}; run with sudo?") from exc


def _write_files(
    box_dir: Path,
    text: str,
    env_text: str,
    secrets: dict[str, str],
    node_pass: str | None,
    generated: tuple[str, ...],
) -> Written:
    """The only part that touches the disk; every input is already validated."""
    config_path = box_dir / CONFIG_FILE
    env_path = box_dir / ENV_FILE
    secrets_dir = box_dir / SECRETS_DIR
    node_pass_path = box_dir / DATA_DIR / MYST_PROVIDER_DATA / NODEUI_PASS_FILE
    result = Written()
    box_dir.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        shutil.copy2(config_path, box_dir / CONFIG_BACKUP)
    result.files.append(write_file(config_path, text, PUBLIC_FILE_MODE))
    result.files.append(write_file(env_path, env_text, PUBLIC_FILE_MODE))
    if node_pass is not None:
        node_pass_path.parent.mkdir(mode=DATA_DIR_MODE, parents=True, exist_ok=True)
        result.files.append(write_file(node_pass_path, node_pass, SECRET_FILE_MODE))
    elif node_pass_path.exists():
        result.retired.append(_retire(node_pass_path))
    # The top-level files belong to the person, not to root: `vibedpn up` rewrites .env and
    # later commands edit config.yaml without sudo. secrets/ stays root-only.
    for path in (config_path, env_path, box_dir / CONFIG_BACKUP):
        if path.exists():
            give_to_invoker(path)
    secrets_dir.mkdir(mode=SECRET_DIR_MODE, exist_ok=True)
    secrets_dir.chmod(SECRET_DIR_MODE)
    for name, content in secrets.items():
        result.files.append(write_file(secrets_dir / name, content, SECRET_FILE_MODE))
    for name in generated:
        path = secrets_dir / name
        if not _present(path):
            token = secrets_module.token_urlsafe(GENERATED_SECRET_BYTES)
            result.files.append(write_file(path, token, SECRET_FILE_MODE))
    for name in KNOWN_SECRETS:
        stale = secrets_dir / name
        if name not in secrets and name not in generated and stale.exists():
            result.retired.append(_retire(stale))
    return result


def _retire(path: Path) -> Path:
    retired = path.with_name(path.name + BACKUP_SUFFIX)
    path.replace(retired)
    retired.chmod(SECRET_FILE_MODE)
    return retired


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


def country_passphrase_file(country: str) -> str:
    return COUNTRY_PASSPHRASE_TEMPLATE.format(country=country.lower())


def country_secrets(config: Config) -> list[str]:
    """The passphrases of the country consumers this configuration runs."""
    channels = config.routing.channels() if config.routing is not None else []
    countries = sorted(
        {item.country for item in channels if item.via.value == "dpn" and item.country}
    )
    return [country_passphrase_file(country) for country in countries]


def ensure_country_secrets(box_dir: Path, config: Config) -> list[Path]:
    """Create the passphrase of every country consumer that has none yet (a country added after
    `init`); an existing one is never replaced — it unlocks that country's identity."""
    secrets_dir = box_dir / SECRETS_DIR
    created = []
    for name in country_secrets(config):
        path = secrets_dir / name
        if _present(path):
            continue
        secrets_dir.mkdir(mode=SECRET_DIR_MODE, exist_ok=True)
        token = secrets_module.token_urlsafe(GENERATED_SECRET_BYTES)
        created.append(write_file(path, token, SECRET_FILE_MODE))
    return created
