"""AdGuard Home configuration: core owns a handful of keys, AdGuard and the owner own the rest.

AdGuard rewrites ``AdGuardHome.yaml`` on its first start — every default spelled out, mode 600,
comments gone — and leaves it alone afterwards; a key changed between two of its starts is
applied (verified on v0.107.79). So core, at its own start and before AdGuard (``depends_on``),
writes a minimal file when there is none and otherwise changes only its keys in place: filters
and settings made in the AdGuard web interface survive every restart of the box.
"""

from __future__ import annotations

import io
from pathlib import Path

from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import YAMLError

from vibedpn.atomic import write_private
from vibedpn.bootstrap import HTPASSWD_FILE, UI_USER
from vibedpn.config import Config, RoutingMode
from vibedpn.config_edit import round_trip_yaml

CONF_FILE = "AdGuardHome.yaml"
# The schema of adguard/adguardhome v0.107.79, the tag compose.yaml pins: a file without it is
# migrated and rewritten, a newer one makes AdGuard refuse to start (docs/knowledge/adguard).
SCHEMA_VERSION = 34
DNS_PORT = 53
# The box name core last published (ui.host_name), kept in core's data dir: AdGuard drops unknown
# keys and comments, so the file itself cannot say which rewrite is ours after a rename.
HOST_NAME_STATE_FILE = "adguard-host-name"


class AdguardError(RuntimeError):
    """A user-facing reason why the AdGuard configuration could not be written."""


def password_hash(htpasswd: str, user: str = UI_USER) -> str:
    """The bcrypt hash of ``user`` from ``secrets/htpasswd``; AdGuard accepts ``$2b$`` as is."""
    for line in htpasswd.splitlines():
        name, separator, hashed = line.strip().partition(":")
        if separator and name == user and hashed:
            return hashed
    raise AdguardError(f"{HTPASSWD_FILE} has no entry for {user}; run `vibedpn init --force`")


def _set_managed(data: CommentedMap, config: Config, hashed: str) -> None:
    network = config.network
    if network is None:  # callers check; keeps the type narrow
        raise AdguardError("AdGuard runs only on a box with a LAN")
    http = data.setdefault("http", CommentedMap())
    http["address"] = f"{network.lan_address}:{config.dns.web_port}"
    users = data.get("users")
    if not isinstance(users, list):
        users = CommentedSeq()
        data["users"] = users
    ours = next(
        (entry for entry in users if isinstance(entry, dict) and entry.get("name") == UI_USER),
        None,
    )
    if ours is None:
        users.append(CommentedMap([("name", UI_USER), ("password", hashed)]))
    else:
        ours["password"] = hashed
    dns = data.setdefault("dns", CommentedMap())
    # Only the LAN address: the stub of systemd-resolved keeps 127.0.0.53:53 without a conflict.
    dns["bind_hosts"] = CommentedSeq([str(network.lan_address)])
    dns["port"] = DNS_PORT
    dns["upstream_dns"] = CommentedSeq(config.dns.upstreams)
    # In full, IPv6 of the devices would bypass the uplinks (docs/knowledge/linux/lanRouter.md).
    dns["aaaa_disabled"] = config.routing is not None and config.routing.mode is RoutingMode.FULL


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
    existing: str | None, config: Config, hashed: str, previous_name: str | None = None
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
    _set_managed(data, config, hashed)
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
    text = adguard_text(existing, config, password_hash(htpasswd), previous)
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
