"""Console entry point of the ``core`` container: load ``config.yaml`` and serve the API.

The API binds loopback only. The ``ui`` container (nginx) exposes it on the LAN interface
with authentication; on a VPS the wg0 side is opened in Stage 3.
"""

import os
import sys
from pathlib import Path

import uvicorn
from pydantic import ValidationError

from vibedpn.api.app import create_app
from vibedpn.config import ConfigError, load_config
from vibedpn.engine.router import RouterError, apply_firewall

API_HOST = "127.0.0.1"
CONFIG_PATH_ENV = "VIBEDPN_CONFIG"
DEFAULT_CONFIG_PATH = Path("/etc/vibedpn/config.yaml")


def main() -> None:
    """Serve ``vibedpn.api.app:app`` on the port from ``api.port`` of the box config.

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
    except RouterError as exc:
        sys.stderr.write(f"vibedpn-core: cannot start: {exc}\n")
        raise SystemExit(os.EX_CONFIG) from None
    uvicorn.run(create_app(config), host=API_HOST, port=config.api.port, log_level="info")
