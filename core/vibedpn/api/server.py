"""Console entry point of the ``core`` container: load ``config.yaml`` and serve the API.

The API binds loopback only. The ``ui`` container (nginx) exposes it on the LAN interface
with authentication; on a VPS the wg0 side is opened in Stage 3.
"""

import os
from pathlib import Path

import uvicorn

from vibedpn.config import load_config

API_HOST = "127.0.0.1"
CONFIG_PATH_ENV = "VIBEDPN_CONFIG"
DEFAULT_CONFIG_PATH = Path("/etc/vibedpn/config.yaml")


def main() -> None:
    """Serve ``vibedpn.api.app:app`` on the port from ``api.port`` of the box config."""
    config_path = Path(os.environ.get(CONFIG_PATH_ENV, DEFAULT_CONFIG_PATH))
    config = load_config(config_path)
    uvicorn.run("vibedpn.api.app:app", host=API_HOST, port=config.api.port, log_level="info")
