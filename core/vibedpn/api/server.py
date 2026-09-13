"""Console entry point of the ``core`` container: load ``config.yaml`` and serve the API.

The full API binds loopback only. The ``ui`` container (nginx) exposes it on the LAN interface
with authentication; on a VPS home boxes reach a read-only part of it, and the node panel, on
the tunnel address (``vibedpn.api.tunnel``).
"""

import os
import sys
from pathlib import Path

from pydantic import ValidationError

from vibedpn.api.app import create_app
from vibedpn.api.tunnel import run_servers
from vibedpn.config import Config, ConfigError, Upstream, load_config
from vibedpn.engine.adguard import AdguardError, ensure_adguard
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


def router_message(config: Config, uplink: Upstream | None) -> str:
    if config.network is None:
        return f"no LAN in this configuration; table {ROUTER_TABLE} removed if it was loaded"
    if uplink is None:
        return f"LAN router applied (table {ROUTER_TABLE}): routing.mode off, LAN goes direct"
    return (
        f"LAN router applied (table {ROUTER_TABLE}): routing.mode full through uplink {uplink};"
        " traffic waits for its gateway to answer"
    )


CONFIG_PATH_ENV = "VIBEDPN_CONFIG"
DEFAULT_CONFIG_PATH = Path("/etc/vibedpn/config.yaml")
SECRETS_DIR_ENV = "VIBEDPN_SECRETS"
DEFAULT_SECRETS_DIR = Path("/etc/vibedpn/secrets")  # compose.yaml mounts ./secrets here
ADGUARD_DIR_ENV = "VIBEDPN_ADGUARD_CONF"
DEFAULT_ADGUARD_DIR = Path("/etc/vibedpn/adguard")  # compose.yaml mounts ./data/adguard/conf


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
        uplink = apply_router(config)
        sys.stderr.write(f"vibedpn-core: {router_message(config, uplink)}\n")
    except RouterError as exc:
        sys.stderr.write(f"vibedpn-core: cannot start: {exc}\n")
        raise SystemExit(os.EX_CONFIG) from None
    secrets_dir = Path(os.environ.get(SECRETS_DIR_ENV, DEFAULT_SECRETS_DIR))
    # Before the API, like the tunnel below: compose starts adguard only once core is healthy.
    adguard_dir = Path(os.environ.get(ADGUARD_DIR_ENV, DEFAULT_ADGUARD_DIR))
    try:
        adguard = ensure_adguard(config, adguard_dir, secrets_dir)
    except AdguardError as exc:
        sys.stderr.write(f"vibedpn-core: cannot start: {exc}\n")
        raise SystemExit(os.EX_CONFIG) from None
    if adguard is not None:
        state = "updated" if adguard else "already current"
        sys.stderr.write(f"vibedpn-core: AdGuard Home configuration {state}\n")
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
    application = create_app(config, secrets_dir=secrets_dir)
    run_servers(config, application, uplink=uplink)
