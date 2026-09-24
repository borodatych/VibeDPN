"""AdGuard Home configuration: core owns a handful of keys, AdGuard and the owner own the rest.

AdGuard rewrites ``AdGuardHome.yaml`` on its first start — every default spelled out, mode 600,
comments gone — and leaves it alone afterwards; a key changed between two of its starts is
applied (verified on v0.107.79). So core, at its own start and before AdGuard (``depends_on``),
writes a minimal file when there is none and otherwise changes only its keys in place: filters
and settings made in the AdGuard web interface survive every restart of the box.
"""

from __future__ import annotations

import io
import os
from collections.abc import Callable
from ipaddress import IPv4Address
from pathlib import Path

import bcrypt
import httpx
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import YAMLError

from vibedpn.atomic import write_private
from vibedpn.bootstrap import ADGUARD_CORE_PASSWORD_FILE, HTPASSWD_FILE, UI_USER
from vibedpn.config import Config, RoutingMode
from vibedpn.config_edit import round_trip_yaml
from vibedpn.engine.querylog import PAGE_LIMIT, QUERYLOG_PATH
from vibedpn.engine.resolver import RESOLVER_HOST, RESOLVER_PORT
from vibedpn.engine.router import ADGUARD_UID
from vibedpn.engine.sockdiag import Connection, Exchange, close_where, netlink_exchange

CONF_FILE = "AdGuardHome.yaml"
# The schema of adguard/adguardhome v0.107.79, the tag compose.yaml pins: a file without it is
# migrated and rewritten, a newer one makes AdGuard refuse to start (docs/knowledge/adguard).
SCHEMA_VERSION = 34
DNS_PORT = 53
# The box name core last published (ui.host_name), kept in core's data dir: AdGuard drops unknown
# keys and comments, so the file itself cannot say which rewrite is ours after a rename.
HOST_NAME_STATE_FILE = "adguard-host-name"
# Core's own AdGuard user: POST /control/dns_config with Basic auth (internal/home/authhttp.go),
# so a mode change reaches AdGuard live; `disable_ipv6` sets AAAADisabled without a DNS restart
# and ConfModifier saves it (internal/dnsforward/http.go, v0.107.79).
CORE_USER = "vibedpn-core"
DNS_CONFIG_PATH = "/control/dns_config"
ADGUARD_API_TIMEOUT_SECONDS = 5.0


class AdguardError(RuntimeError):
    """A user-facing reason why the AdGuard configuration could not be written."""


def password_hash(htpasswd: str, user: str = UI_USER) -> str:
    """The bcrypt hash of ``user`` from ``secrets/htpasswd``; AdGuard accepts ``$2b$`` as is."""
    for line in htpasswd.splitlines():
        name, separator, hashed = line.strip().partition(":")
        if separator and name == user and hashed:
            return hashed
    raise AdguardError(f"{HTPASSWD_FILE} has no entry for {user}; run `vibedpn init --force`")


def _set_user(users: CommentedSeq, name: str, hashed: str) -> None:
    entry = next(
        (item for item in users if isinstance(item, dict) and item.get("name") == name), None
    )
    if entry is None:
        users.append(CommentedMap([("name", name), ("password", hashed)]))
    else:
        entry["password"] = hashed


def core_user_hash(existing: str | None, password: str) -> str:
    """A bcrypt hash of core's AdGuard password: the stored one while it still matches, so a
    restart of core does not rewrite the file with a new salt every time."""
    if existing:
        try:
            if bcrypt.checkpw(password.encode("utf-8"), existing.encode("ascii")):
                return existing
        except ValueError:
            pass
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def _set_managed(
    data: CommentedMap, config: Config, hashed: str, core_password: str | None = None
) -> None:
    network = config.network
    if network is None:  # callers check; keeps the type narrow
        raise AdguardError("AdGuard runs only on a box with a LAN")
    http = data.setdefault("http", CommentedMap())
    http["address"] = f"{network.lan_address}:{config.dns.web_port}"
    users = data.get("users")
    if not isinstance(users, list):
        users = CommentedSeq()
        data["users"] = users
    _set_user(users, UI_USER, hashed)
    if core_password is not None:
        stored = next(
            (
                str(item.get("password", ""))
                for item in users
                if isinstance(item, dict) and item.get("name") == CORE_USER
            ),
            None,
        )
        _set_user(users, CORE_USER, core_user_hash(stored, core_password))
    dns = data.setdefault("dns", CommentedMap())
    # Only the LAN address: the stub of systemd-resolved keeps 127.0.0.53:53 without a conflict.
    dns["bind_hosts"] = CommentedSeq([str(network.lan_address)])
    dns["port"] = DNS_PORT
    upstreams, fallbacks = dns_upstreams(config)
    dns["upstream_dns"] = CommentedSeq(upstreams)
    dns["fallback_dns"] = CommentedSeq(fallbacks)
    # In full, IPv6 of the devices would bypass the uplinks (docs/knowledge/linux/lanRouter.md).
    dns["aaaa_disabled"] = config.routing is not None and config.routing.mode is RoutingMode.FULL


def dns_upstreams(config: Config) -> tuple[list[str], list[str]]:
    """``upstream_dns`` and ``fallback_dns``: in smart the resolver of core asks the DoH servers and
    fills the channel sets; the DoH servers stay as fallback, so DNS lives without core
    (docs/decisions.md, 17)."""
    if config.routing is not None and config.routing.mode is RoutingMode.SMART:
        return [f"{RESOLVER_HOST}:{RESOLVER_PORT}"], list(config.dns.upstreams)
    return list(config.dns.upstreams), []


def _set_box_name(data: CommentedMap, config: Config, previous: str | None) -> None:
    """Point ``ui.host_name`` at the box: one rewrite of ours (the previous name's is dropped),
    the owner's rewrites untouched; without a panel, no rewrite of ours."""
    network = config.network
    if network is None:  # callers check; keeps the type narrow
        raise AdguardError("AdGuard runs only on a box with a LAN")
    filtering = data.setdefault("filtering", CommentedMap())
    rewrites = filtering.get("rewrites")
    if not isinstance(rewrites, list):
        rewrites = CommentedSeq()
        filtering["rewrites"] = rewrites
    ours = {config.ui.host_name, previous}
    kept = [
        entry for entry in rewrites if not (isinstance(entry, dict) and entry.get("domain") in ours)
    ]
    del rewrites[:]
    rewrites.extend(kept)
    if not config.ui.enabled:
        return
    # `enabled` is required: v0.107.79 skips a rewrite without it (filtering/rewrites.go).
    rewrites.append(
        CommentedMap(
            [
                ("domain", config.ui.host_name),
                ("answer", str(network.lan_address)),
                ("enabled", True),
            ]
        )
    )


def adguard_text(
    existing: str | None,
    config: Config,
    hashed: str,
    previous_name: str | None = None,
    core_password: str | None = None,
) -> str:
    """The new file: a minimal one, or ``existing`` with only core's keys changed."""
    yaml = round_trip_yaml()
    if existing is None:
        data = CommentedMap([("schema_version", SCHEMA_VERSION)])
    else:
        try:
            data = yaml.load(existing)
        except YAMLError as exc:
            raise AdguardError(f"{CONF_FILE} is not valid YAML: {exc}") from exc
        if not isinstance(data, dict):
            raise AdguardError(f"{CONF_FILE}: the top level must be a mapping")
        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            raise AdguardError(
                f"{CONF_FILE} has schema_version {version}, but this VibeDPN manages"
                f" {SCHEMA_VERSION} (adguard/adguardhome v0.107.79); leaving it untouched —"
                " restore data/adguard/conf from a backup or pin the image tag back"
            )
    _set_managed(data, config, hashed, core_password)
    _set_box_name(data, config, previous_name)
    buffer = io.StringIO()
    yaml.dump(data, buffer)
    return buffer.getvalue()


def ensure_adguard(
    config: Config, conf_dir: Path, secrets_dir: Path, data_dir: Path
) -> bool | None:
    """Bring ``AdGuardHome.yaml`` in line with config.yaml; ``None`` when this box runs no
    AdGuard, otherwise whether the file changed. ``data_dir`` keeps the published box name."""
    if config.network is None or not config.dns.enabled:
        return None
    try:
        htpasswd = (secrets_dir / HTPASSWD_FILE).read_text(encoding="utf-8")
    except OSError as exc:
        raise AdguardError(f"cannot read {HTPASSWD_FILE}: {exc.strerror or exc}") from exc
    path = conf_dir / CONF_FILE
    try:
        existing = path.read_text(encoding="utf-8") if path.exists() else None
    except OSError as exc:
        raise AdguardError(f"cannot read {path}: {exc.strerror or exc}") from exc
    state = data_dir / HOST_NAME_STATE_FILE
    try:
        previous = state.read_text(encoding="utf-8").strip() or None if state.exists() else None
    except OSError as exc:
        raise AdguardError(f"cannot read {state}: {exc.strerror or exc}") from exc
    core_password = read_core_password(secrets_dir)
    text = adguard_text(existing, config, password_hash(htpasswd), previous, core_password)
    try:
        conf_dir.mkdir(parents=True, exist_ok=True)
        changed = write_private(path, text)
        # After the file: a crash in between leaves the old name recorded, and the next start
        # still finds and replaces that rewrite.
        data_dir.mkdir(parents=True, exist_ok=True)
        if config.ui.enabled:
            write_private(state, config.ui.host_name + "\n")
        else:
            state.unlink(missing_ok=True)
    except OSError as exc:
        raise AdguardError(f"cannot write {exc.filename or path}: {exc.strerror or exc}") from exc
    return changed


def read_core_password(secrets_dir: Path) -> str:
    path = secrets_dir / ADGUARD_CORE_PASSWORD_FILE
    try:
        password = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise AdguardError(
            f"cannot read {ADGUARD_CORE_PASSWORD_FILE}: {exc.strerror or exc};"
            " run `vibedpn init --force`"
        ) from exc
    if not password:
        raise AdguardError(f"{ADGUARD_CORE_PASSWORD_FILE} is empty; run `vibedpn init --force`")
    return password


def set_dns_mode(
    config: Config,
    secrets_dir: Path,
    transport: httpx.BaseTransport | None = None,
    *,
    upstreams_changed: bool = False,
) -> bool | None:
    """Tell the running AdGuard the DNS mode of ``routing.mode``; ``None`` when this box runs no
    AdGuard, ``True`` once it accepted. The file carries the same values for its next start.
    The upstreams go only when smart came or went: changing them restarts AdGuard's DNS server."""
    network = config.network
    if network is None or not config.dns.enabled:
        return None
    password = read_core_password(secrets_dir)
    disabled = config.routing is not None and config.routing.mode is RoutingMode.FULL
    body: dict[str, object] = {"disable_ipv6": disabled}
    if upstreams_changed:
        upstreams, fallbacks = dns_upstreams(config)
        body |= {"upstream_dns": upstreams, "fallback_dns": fallbacks}
    url = f"http://{network.lan_address}:{config.dns.web_port}{DNS_CONFIG_PATH}"
    try:
        with httpx.Client(
            timeout=ADGUARD_API_TIMEOUT_SECONDS, transport=transport, trust_env=False
        ) as client:
            response = client.post(url, json=body, auth=(CORE_USER, password))
    except httpx.HTTPError as exc:
        raise AdguardError(f"AdGuard does not answer at {url}: {exc.__class__.__name__}") from exc
    if response.status_code != httpx.codes.OK:
        raise AdguardError(f"AdGuard refused the DNS mode: HTTP {response.status_code}")
    return True


def close_upstream_connections(config: Config, exchange: Exchange = netlink_exchange) -> int:
    """Close the connections AdGuard holds to its upstreams; how many closed

    Called when the uplink of its queries changed: each would fail the first query riding on it
    Unlike a restart of its DNS server, this keeps its cache and never takes its listener down
    Peers in the LAN and on the box stay: chain dns_uplink leaves them unmarked
    Every IPv6 peer but loopback goes: in full its IPv6 is dropped silently, not reset
    """
    network = config.network
    if network is None or not config.dns.enabled:
        return 0

    def upstream(connection: Connection) -> bool:
        peer = connection.peer
        if peer.is_loopback or peer == connection.local:
            return False
        return not (isinstance(peer, IPv4Address) and peer in network.lan_subnet)

    return close_where(ADGUARD_UID, upstream, exchange)


Chown = Callable[[Path, int, int], None]


def give_to_adguard(directories: list[Path], uid: int, chown: Chown = os.chown) -> int:
    """Hand the directories of AdGuard, and everything inside, to its user; returns how many
    entries changed owner. Boxes set up before AdGuard had its own user hold root-owned files."""
    changed = 0
    for directory in directories:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            entries = [directory, *directory.rglob("*")]
            for entry in entries:
                stat = entry.lstat()
                if stat.st_uid != uid or stat.st_gid != uid:
                    chown(entry, uid, uid)
                    changed += 1
        except OSError as exc:
            raise AdguardError(
                f"cannot hand {exc.filename or directory} to AdGuard: {exc.strerror or exc}"
            ) from exc
    return changed


def querylog_fetcher(
    config: Config, secrets_dir: Path, transport: httpx.BaseTransport | None = None
) -> Callable[[str | None], object]:
    """One page of AdGuard's query log as JSON, as core's own AdGuard user; ``older_than`` pages
    back from a record time."""
    network = config.network
    if network is None:
        raise AdguardError("AdGuard runs only on a box with a LAN")
    url = f"http://{network.lan_address}:{config.dns.web_port}{QUERYLOG_PATH}"
    client = httpx.Client(timeout=ADGUARD_API_TIMEOUT_SECONDS, transport=transport, trust_env=False)

    def fetch(older_than: str | None) -> object:
        params: dict[str, str | int] = {"limit": PAGE_LIMIT}
        if older_than is not None:
            params["older_than"] = older_than
        try:
            response = client.get(
                url, params=params, auth=(CORE_USER, read_core_password(secrets_dir))
            )
        except httpx.HTTPError as exc:
            raise OSError(f"AdGuard does not answer at {url}: {exc.__class__.__name__}") from exc
        if response.status_code != httpx.codes.OK:
            raise OSError(f"AdGuard refused its query log: HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise OSError("AdGuard answered its query log with something that is not JSON") from exc

    return fetch
