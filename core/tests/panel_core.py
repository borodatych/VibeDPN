"""A core for the end-to-end tests of the panel (ui/src/test/setup/e2e.ts)

The real API of a home box with two exits, on a data directory of its own:
The pages have something to show

Run as ``python -m tests.panel_core <port> <data dir>`` from core/
Nothing here touches the host: the router, the firewall and the tunnel are left alone
"""

from __future__ import annotations

import sys
from pathlib import Path

import uvicorn

from vibedpn.api.app import create_app
from vibedpn.config import Config
from vibedpn.engine.logs import SERVICES_FILE

from .conftest import home_config

# What `vibedpn up` tells core on such a box: the panel offers the logs of these
SERVICES = ("adguard", "core", "myst-consumer", "tor")


def main() -> None:
    port, data = int(sys.argv[1]), Path(sys.argv[2])
    data.mkdir(parents=True, exist_ok=True)
    (data / SERVICES_FILE).write_text("".join(f"{name}\n" for name in SERVICES), encoding="utf-8")
    # Tor in use and DPN idle: the exit cards differ in how many lines their values run to
    config = home_config() | {
        "routing": {"mode": "full", "default_upstream": "tor"},
        "upstreams": {"dpn": {"enabled": True}, "tor": {"enabled": True}},
    }
    application = create_app(Config.model_validate(config), data_dir=data)
    uvicorn.run(application, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
