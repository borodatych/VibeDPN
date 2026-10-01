"""A core for the end-to-end tests of the panel (ui/src/test/setup/e2e.ts)

The real API of a home box with four exits, on a data directory of its own:
The pages have something to show

Run as ``python -m tests.panel_core <port> <box dir>`` from core/
Nothing here touches the host: the router, the firewall and the tunnel are left alone
"""

from __future__ import annotations

import sys
import time
from ipaddress import IPv4Address
from pathlib import Path

import uvicorn

from vibedpn.api.app import create_app
from vibedpn.api.state import BoxState
from vibedpn.bootstrap import XRAY_LINK_FILE, render_config
from vibedpn.config import Config
from vibedpn.detect import Interface
from vibedpn.engine.backup import BACKUPS_DIR
from vibedpn.engine.devices import DB_FILE, DeviceStore, Neighbour
from vibedpn.engine.events import DB_FILE as EVENTS_FILE
from vibedpn.engine.events import Event, EventAction, EventKind, EventStore
from vibedpn.engine.hostapd import PASSPHRASE_FILE as WIFI_PASSPHRASE_FILE
from vibedpn.engine.logs import SERVICES_FILE
from vibedpn.engine.wifi import Station

from .conftest import home_config
from .test_apply import PROVIDER_FILE as PROTON_FILE
from .test_telegram_bot import Box as BotBox

# A share link of a made-up server: the masking exit is on, so the panel offers it as a channel
XRAY_LINK = (
    "vless://11111111-2222-3333-4444-555555555555@exit.example.org:443"
    "?security=reality&sni=a.example&pbk=key#stand\n"
)

# Devices of the LAN the box has seen, and the names their addresses resolve to
DEVICES = [
    Neighbour("aa:bb:cc:00:00:01", IPv4Address("192.168.50.21")),
    Neighbour("aa:bb:cc:00:00:02", IPv4Address("192.168.50.22")),
    Neighbour("aa:bb:cc:00:00:03", IPv4Address("192.168.50.23")),
]
NAMES = {"192.168.50.21": "anna-phone.lan", "192.168.50.22": "living-room-tv.lan"}


ETH0 = Interface("eth0", IPv4Address("192.168.1.50"), 24)
WLAN0 = Interface("wlan0", IPv4Address("192.168.50.1"), 24)
STATIONS = [Station("aa:bb:cc:00:00:01", 3600, -56, 120, 48_000_000, 2_100_000)]


def stand_events(now: float) -> list[Event]:
    """A Wi-Fi client and an exit that dropped out and came back: rows of each kind"""
    return [
        Event(now - 3600, EventKind.WIFI, "aa:bb:cc:00:00:01", EventAction.CLIENT_CONNECTED),
        Event(now - 1800, EventKind.UPLINK, "tor", EventAction.GATEWAY_SILENT),
        Event(now - 1700, EventKind.UPLINK, "tor", EventAction.GATEWAY_ANSWERS),
        Event(now - 600, EventKind.WIFI, "aa:bb:cc:00:00:01", EventAction.CLIENT_DISCONNECTED),
    ]


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
            # a box in the break of its own Wi-Fi LAN, the access server on: each page has a subject
            "network": {
                "mode": "gateway",
                "lan_interface": "wlan0",
                "lan_subnet": "192.168.50.0/24",
                "lan_address": "192.168.50.1",
                "wan_interface": "eth0",
                "wifi": {"ssid": "Home", "country": "de"},
            },
            "access": {"enabled": True, "address": "home.example.org"},
            "routing": {
                "mode": "full",
                "default_upstream": "tor",
                # a few rules of each kind: the tables of «Rules» are not empty
                "domains": [
                    {"domain": "kinopoisk.ru", "via": "direct"},
                    {"domain": "youtube.com", "via": "tor"},
                ],
                "networks": [{"network": "149.154.160.0/20", "via": "tor"}],
            },
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
    (secrets / WIFI_PASSPHRASE_FILE).write_text("stand-wifi-passphrase\n", encoding="utf-8")
    backups = box / BACKUPS_DIR
    backups.mkdir(exist_ok=True)
    (backups / "vibedpn-20260930-031500.tar.gz").write_bytes(b"\0" * 2048)
    devices = DeviceStore(data / DB_FILE)
    devices.record(DEVICES, time.time(), NAMES.get)
    events = EventStore(data / EVENTS_FILE)
    for event in stand_events(time.time()):
        events.add(event)
    path = box / "config.yaml"
    path.write_text(render_config(config), encoding="utf-8")
    # what the panel saves goes into config.yaml of this box; nothing is applied to the host
    state = BoxState(config, path, apply=lambda _config: [])
    # a bot linked to a chat, talking to a fake Telegram: the notification page shows its settings
    bot = BotBox(box, config, linked=True).bot
    application = create_app(
        config,
        state=state,
        secrets_dir=secrets,
        data_dir=data,
        telegram=bot,
        device_store=devices,
        events=events,
        access_dir=box / "access",
        access_owner=None,
        hostapd_dir=box / "hostapd",
        backups_dir=backups,
        # the host's `ip` and the access point's socket are not on a developer's machine
        interfaces_source=lambda: (ETH0, [ETH0, WLAN0]),
        wifi_stations=lambda _interface: STATIONS,
    )
    uvicorn.run(application, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
