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
from vibedpn.config import ConfigError, load_config
from vibedpn.engine.router import (
    EGRESS_TABLE,
    Egress,
    RouterError,
    apply_firewall,
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
CONFIG_PATH_ENV = "VIBEDPN_CONFIG"
DEFAULT_CONFIG_PATH = Path("/etc/vibedpn/config.yaml")
SECRETS_DIR_ENV = "VIBEDPN_SECRETS"
DEFAULT_SECRETS_DIR = Path("/etc/vibedpn/secrets")  # compose.yaml mounts ./secrets here


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
    except RouterError as exc:
        sys.stderr.write(f"vibedpn-core: cannot start: {exc}\n")
        raise SystemExit(os.EX_CONFIG) from None
    # Before the API: compose starts wg-server only once core is healthy, so the file it reads
    # is always the one rendered from the current config.
    secrets_dir = Path(os.environ.get(SECRETS_DIR_ENV, DEFAULT_SECRETS_DIR))
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
    run_servers(config, application)
