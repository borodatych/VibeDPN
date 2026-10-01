"""A core for the end-to-end tests of the panel (ui/src/test/setup/e2e.ts)

The real API of a home box with four exits, on a data directory of its own:
The pages have something to show

Run as ``python -m tests.panel_core <port> <box dir>`` from core/
Nothing here touches the host: the router, the firewall and the tunnel are left alone
"""

from __future__ import annotations

import sys
from pathlib import Path

import uvicorn

from vibedpn.api.app import create_app
from vibedpn.api.state import BoxState
from vibedpn.bootstrap import XRAY_LINK_FILE, render_config
from vibedpn.config import Config
from vibedpn.engine.logs import SERVICES_FILE

from .conftest import home_config
from .test_apply import PROVIDER_FILE as PROTON_FILE
from .test_telegram_bot import Box as BotBox

# A share link of a made-up server: the masking exit is on, so the panel offers it as a channel
XRAY_LINK = (
    "vless://11111111-2222-3333-4444-555555555555@exit.example.org:443"
    "?security=reality&sni=a.example&pbk=key#stand\n"
)

# What `vibedpn up` tells core on such a box: the panel offers the logs of these
SERVICES = ("adguard", "core", "myst-consumer", "tor")


def main() -> None:
    port, box = int(sys.argv[1]), Path(sys.argv[2])
    data, secrets = box / "data", box / "secrets"
    data.mkdir(parents=True, exist_ok=True)
    secrets.mkdir(mode=0o700, exist_ok=True)
    (data / SERVICES_FILE).write_text("".join(f"{name}\n" for name in SERVICES), encoding="utf-8")
    # Tor in use, the other exits idle: the exit cards differ in how many lines their values take
    config = Config.model_validate(
        home_config()
        | {
            "routing": {"mode": "full", "default_upstream": "tor"},
            "upstreams": {
                "dpn": {"enabled": True},
                "tor": {"enabled": True},
                "wg": {"proton": {}},
                "xray": {"enabled": True},
            },
        }
    )
    (secrets / "wg-proton.conf").write_text(PROTON_FILE, encoding="utf-8")
    (secrets / XRAY_LINK_FILE).write_text(XRAY_LINK, encoding="utf-8")
    path = box / "config.yaml"
    path.write_text(render_config(config), encoding="utf-8")
    # what the panel saves goes into config.yaml of this box; nothing is applied to the host
    state = BoxState(config, path, apply=lambda _config: [])
    # a bot linked to a chat, talking to a fake Telegram: the notification page shows its settings
    bot = BotBox(box, config, linked=True).bot
    application = create_app(config, state=state, secrets_dir=secrets, data_dir=data, telegram=bot)
    uvicorn.run(application, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
