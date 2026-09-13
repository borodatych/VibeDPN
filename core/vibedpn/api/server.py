"""Console entry point of the ``core`` container: load ``config.yaml`` and serve the API.

The full API binds loopback only. The ``ui`` panel exposes it on the LAN interface under
``/api/core/`` to a signed-in session; on a VPS home boxes reach a read-only part of it, and the
node panel, on the tunnel address (``vibedpn.api.tunnel``).
"""

import os
import sys
from collections.abc import Callable, Coroutine
from functools import partial
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from vibedpn.api.app import create_app
from vibedpn.api.consumer import ConsumerStatus, consumer_round, watch_consumer
from vibedpn.api.state import BoxState
from vibedpn.api.tunnel import run_servers
from vibedpn.api.uplink import UplinkWatchers
from vibedpn.config import Config, ConfigError, Upstream, load_config
from vibedpn.engine.adguard import AdguardError, ensure_adguard
from vibedpn.engine.devices import DB_FILE, DeviceError, DeviceStore
from vibedpn.engine.dnsmasq import DnsmasqError, ensure_dnsmasq
from vibedpn.engine.router import (
    EGRESS_TABLE,
    ROUTER_TABLE,
    Egress,
    RouterError,
    apply_firewall,
    apply_router,
    apply_tunnel_egress,
)
from vibedpn.engine.wg import WgError, ensure_server

EGRESS_MESSAGES = {
    Egress.NONE: f"no tunnel in this configuration; table {EGRESS_TABLE} removed if it was loaded",
    Egress.DOCKER_USER: (
        f"tunnel egress applied (table {EGRESS_TABLE}, forward opened in DOCKER-USER)"
    ),
    Egress.NO_DOCKER_DROP: (
        f"tunnel egress applied (table {EGRESS_TABLE}; no DOCKER-USER chain, nothing to open)"
    ),
}


def router_message(config: Config, uplinks: list[Upstream]) -> str:
    if config.network is None:
        return f"no LAN in this configuration; table {ROUTER_TABLE} removed if it was loaded"
    mode = config.routing.mode.value if config.routing is not None else "off"
    if not uplinks:
        return f"LAN router applied (table {ROUTER_TABLE}): routing.mode {mode}, LAN goes direct"
    names = ", ".join(uplink.value for uplink in uplinks)
    return (
        f"LAN router applied (table {ROUTER_TABLE}): routing.mode {mode}, uplinks in use: {names};"
        " their traffic waits for the gateways to answer"
    )


CONFIG_PATH_ENV = "VIBEDPN_CONFIG"
# compose.yaml mounts the box directory: core rewrites config.yaml atomically, which a rename over
# a single bind-mounted file does not allow (EBUSY).
DEFAULT_CONFIG_PATH = Path("/etc/vibedpn/box/config.yaml")
SECRETS_DIR_ENV = "VIBEDPN_SECRETS"
DEFAULT_SECRETS_DIR = Path("/etc/vibedpn/secrets")  # compose.yaml mounts ./secrets here
ADGUARD_DIR_ENV = "VIBEDPN_ADGUARD_CONF"
DEFAULT_ADGUARD_DIR = Path("/etc/vibedpn/adguard")  # compose.yaml mounts ./data/adguard/conf
DATA_DIR_ENV = "VIBEDPN_DATA"
DNSMASQ_DIR_ENV = "VIBEDPN_DNSMASQ_CONF"
DEFAULT_DNSMASQ_DIR = Path("/etc/vibedpn/dnsmasq")  # compose.yaml mounts ./data/dnsmasq
DEFAULT_DATA_DIR = Path("/var/lib/vibedpn")  # compose.yaml mounts ./data/core


def main() -> None:
    """Serve the API on the port from ``api.port`` of the box config.

    A missing or invalid config is a user error: one readable message, exit code ``EX_CONFIG``.
    """
    config_path = Path(os.environ.get(CONFIG_PATH_ENV, DEFAULT_CONFIG_PATH))
    try:
        config = load_config(config_path)
    except (ConfigError, ValidationError) as exc:
        sys.stderr.write(f"vibedpn-core: cannot start: {exc}\n")
        raise SystemExit(os.EX_CONFIG) from None
    try:
        if apply_firewall(config):
            sys.stderr.write("vibedpn-core: host firewall applied (table inet vibedpn)\n")
        else:
            sys.stderr.write(
                "vibedpn-core: no host firewall in this configuration;"
                " table inet vibedpn removed if it was loaded\n"
            )
        egress = apply_tunnel_egress(config)
        sys.stderr.write(f"vibedpn-core: {EGRESS_MESSAGES[egress]}\n")
        uplinks = apply_router(config)
        sys.stderr.write(f"vibedpn-core: {router_message(config, uplinks)}\n")
    except RouterError as exc:
        sys.stderr.write(f"vibedpn-core: cannot start: {exc}\n")
        raise SystemExit(os.EX_CONFIG) from None
    secrets_dir = Path(os.environ.get(SECRETS_DIR_ENV, DEFAULT_SECRETS_DIR))
    # Before the API, like the tunnel below: compose starts adguard only once core is healthy.
    adguard_dir = Path(os.environ.get(ADGUARD_DIR_ENV, DEFAULT_ADGUARD_DIR))
    data_dir = Path(os.environ.get(DATA_DIR_ENV, DEFAULT_DATA_DIR))
    try:
        adguard = ensure_adguard(config, adguard_dir, secrets_dir, data_dir)
    except AdguardError as exc:
        sys.stderr.write(f"vibedpn-core: cannot start: {exc}\n")
        raise SystemExit(os.EX_CONFIG) from None
    _report("AdGuard Home", adguard)
    _report("dnsmasq", _write_dnsmasq(config))
    # Before the API: compose starts wg-server only once core is healthy, so the file it reads
    # is always the one rendered from the current config.
    try:
        files = ensure_server(config, secrets_dir)
    except WgError as exc:
        sys.stderr.write(f"vibedpn-core: cannot start: {exc}\n")
        raise SystemExit(os.EX_CONFIG) from None
    if files is not None:
        sys.stderr.write(f"vibedpn-core: WireGuard server config rendered ({files.conf.name})\n")
        for moved in files.renumbered:
            # The owner changed wg_server.subnet: this box needs its peer file exported again.
            sys.stderr.write(
                f"vibedpn-core: peer {moved.name} moved from {moved.old} to {moved.new};"
                f" run `vibedpn peer export {moved.name}` for its home box\n"
            )
    devices = None
    if config.network is not None:
        try:
            devices = DeviceStore(data_dir / DB_FILE)
        except DeviceError as exc:
            sys.stderr.write(f"vibedpn-core: cannot start: {exc}\n")
            raise SystemExit(os.EX_CONFIG) from None
    watchers = UplinkWatchers(uplinks)
    box_state = BoxState(config, config_path, watchers=watchers)
    consumer = ConsumerStatus()
    application = create_app(
        config,
        secrets_dir=secrets_dir,
        device_store=devices,
        state=box_state,
        watchers=watchers,
        consumer=consumer,
    )
    run_servers(
        config,
        application,
        watchers=watchers,
        devices=devices,
        extra=_consumer_task(config, box_state, consumer, secrets_dir),
    )


def _consumer_task(
    config: Config, box_state: BoxState, consumer: ConsumerStatus, secrets_dir: Path
) -> list[Callable[[], Coroutine[Any, Any, None]]]:
    """The dpn consumer round on a box with a LAN; it idles while uplink dpn is off."""
    if config.network is None:
        return []
    step = consumer_round(secrets_dir)
    return [partial(watch_consumer, lambda: box_state.config, consumer, step)]


def _report(what: str, written: bool | None) -> None:
    if written is not None:
        state = "updated" if written else "already current"
        sys.stderr.write(f"vibedpn-core: {what} configuration {state}\n")


def _write_dnsmasq(config: Config) -> bool | None:
    """Before the API, like AdGuard: compose starts dnsmasq only once core is healthy."""
    conf_dir = Path(os.environ.get(DNSMASQ_DIR_ENV, DEFAULT_DNSMASQ_DIR))
    try:
        written = ensure_dnsmasq(config, conf_dir)
    except DnsmasqError as exc:
        sys.stderr.write(f"vibedpn-core: cannot start: {exc}\n")
        raise SystemExit(os.EX_CONFIG) from None
    return written
