"""LAN devices: the neighbour table as printed on a VM, the SQLite store, discovery, API, CLI."""

import asyncio
import sqlite3
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from vibedpn import cli
from vibedpn.api import client as core_api
from vibedpn.api import discovery
from vibedpn.api.app import create_app
from vibedpn.api.client import DeviceRequestError, list_devices
from vibedpn.api.models import DeviceView
from vibedpn.bootstrap import render_config
from vibedpn.config import Config
from vibedpn.device_view import render_devices
from vibedpn.engine.devices import (
    DeviceError,
    DeviceStore,
    Neighbour,
    parse_neighbours,
)

from .conftest import client_config, vps_config

SUBNET = IPv4Network("192.168.88.0/24")
BOX = IPv4Address("192.168.88.1")
# `ip -j neigh show dev lanp0 nud all` on the colima VM (iproute2 6.1.0, 2026-09-13): a device that
# talked to the box, an address nobody has, and multicast entries.
LISTING = (
    '[{"dst":"224.0.0.22","lladdr":"01:00:5e:00:00:16","state":["NOARP"]},'
    '{"dst":"192.168.88.9","state":["FAILED"]},'
    '{"dst":"192.168.88.2","lladdr":"f6:5f:32:9d:fc:41","state":["DELAY"]},'
    '{"dst":"ff02::2","lladdr":"33:33:00:00:00:02","state":["NOARP"]}]'
)


def test_only_answering_lan_neighbours_are_devices() -> None:
    assert parse_neighbours(LISTING, SUBNET, BOX) == [
        Neighbour("f6:5f:32:9d:fc:41", IPv4Address("192.168.88.2"))
    ]
    elsewhere = LISTING.replace("192.168.88.2", "10.0.0.2")
    assert parse_neighbours(elsewhere, SUBNET, BOX) == []
    itself = LISTING.replace("192.168.88.2", "192.168.88.1")
    assert parse_neighbours(itself, SUBNET, BOX) == []
    with pytest.raises(DeviceError, match="no JSON"):
        parse_neighbours("garbage", SUBNET, BOX)


def test_store_keeps_first_seen_and_looks_names_up_only_when_needed(tmp_path: Path) -> None:
    lookups: list[str] = []

    def resolve(address: str) -> str | None:
        lookups.append(address)
        return f"host-{address.rsplit('.', 1)[1]}"

    store = DeviceStore(tmp_path / "devices.db")
    phone = Neighbour("f6:5f:32:9d:fc:41", IPv4Address("192.168.88.2"))
    assert store.record([phone], 100.0, resolve) == [phone.mac]
    assert store.record([phone], 130.0, resolve) == []
    moved = Neighbour(phone.mac, IPv4Address("192.168.88.7"))
    store.record([moved], 160.0, resolve)
    assert lookups == ["192.168.88.2", "192.168.88.7"]  # new device, then a changed address only
    reopened = DeviceStore(tmp_path / "devices.db").devices()
    assert len(reopened) == 1
    seen = reopened[0]
    assert (seen.ip, seen.hostname, seen.first_seen, seen.last_seen) == (
        IPv4Address("192.168.88.7"),
        "host-7",
        100.0,
        160.0,
    )


def test_a_newer_schema_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "devices.db"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version = 9")
    with pytest.raises(DeviceError, match="schema version 9"):
        DeviceStore(path)


class StopDiscoveryError(Exception):
    pass


def test_discovery_logs_a_failure_once_and_keeps_going(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = Config.model_validate(client_config())
    store = DeviceStore(tmp_path / "devices.db")
    answers: list[DeviceError | str] = [
        DeviceError("ip neigh failed"),
        DeviceError("ip neigh failed"),
        LISTING,
    ]
    rounds = [0]

    def read(interface: str) -> str:
        assert interface == "eth0"
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer.replace("192.168.88.", "192.168.1.")

    async def sleep(_seconds: float) -> None:
        rounds[0] += 1
        if not answers:
            raise StopDiscoveryError

    with pytest.raises(StopDiscoveryError):
        asyncio.run(
            discovery.watch_devices(config, store, read=read, resolve=lambda _a: None, sleep=sleep)
        )
    err = capsys.readouterr().err
    assert err.count("device discovery: ip neigh failed") == 1
    assert "new LAN device f6:5f:32:9d:fc:41" in err
    assert [str(item.ip) for item in store.devices()] == ["192.168.1.2"]


def test_api_names_devices_from_config_by_mac_then_by_address(tmp_path: Path) -> None:
    raw = client_config()
    raw["devices"] = [
        {"name": "phone", "mac": "F6:5F:32:9D:FC:41", "policy": "bypass"},
        {"name": "tv", "ip": "192.168.1.9", "policy": "block"},
    ]
    config = Config.model_validate(raw)
    store = DeviceStore(tmp_path / "devices.db")
    store.record(
        [
            Neighbour("f6:5f:32:9d:fc:41", IPv4Address("192.168.1.2")),
            Neighbour("aa:bb:cc:dd:ee:09", IPv4Address("192.168.1.9")),
            Neighbour("aa:bb:cc:dd:ee:03", IPv4Address("192.168.1.3")),
        ],
        200.0,
        lambda address: "laptop.lan" if address.endswith(".3") else None,
    )
    response = TestClient(create_app(config, device_store=store)).get("/devices")
    assert response.status_code == 200
    by_mac = {item["mac"]: item for item in response.json()}
    assert (by_mac["f6:5f:32:9d:fc:41"]["name"], by_mac["f6:5f:32:9d:fc:41"]["policy"]) == (
        "phone",
        "bypass",
    )
    assert (by_mac["aa:bb:cc:dd:ee:09"]["name"], by_mac["aa:bb:cc:dd:ee:09"]["policy"]) == (
        "tv",
        "block",
    )
    assert by_mac["aa:bb:cc:dd:ee:03"]["name"] is None
    assert by_mac["aa:bb:cc:dd:ee:03"]["hostname"] == "laptop.lan"
    vps = Config.model_validate(vps_config())
    assert TestClient(create_app(vps, device_store=store)).get("/devices").status_code == 404


def test_client_and_cli_list_devices(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = Config.model_validate(client_config())
    store = DeviceStore(tmp_path / "devices.db")
    store.record(
        [Neighbour("f6:5f:32:9d:fc:41", IPv4Address("192.168.1.2"))], 300.0, lambda _a: "phone.lan"
    )
    app = TestClient(create_app(config, device_store=store))

    def core(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/devices"
        answer = app.get("/devices")
        return httpx.Response(answer.status_code, content=answer.content)

    devices = list_devices(4480, transport=httpx.MockTransport(core))
    assert [(item.mac, item.hostname) for item in devices] == [("f6:5f:32:9d:fc:41", "phone.lan")]
    refused = httpx.MockTransport(
        lambda _r: httpx.Response(404, json={"detail": "this box routes no LAN"})
    )
    with pytest.raises(DeviceRequestError, match="routes no LAN"):
        list_devices(4480, transport=refused)

    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    (tmp_path / "config.yaml").write_text(render_config(config), encoding="utf-8")
    monkeypatch.setattr(core_api, "list_devices", lambda _port: devices)
    result = CliRunner().invoke(cli.app, ["device", "list", "--dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "phone.lan" in result.output and "192.168.1.2" in result.output


def test_a_policy_for_a_device_not_seen_yet_is_listed(tmp_path: Path) -> None:
    raw = client_config()
    raw["devices"] = [
        {"name": "phone", "mac": "F6:5F:32:9D:FC:41", "policy": "bypass"},
        {"name": "printer", "ip": "192.168.1.77", "policy": "block"},
        {"name": "old-tv", "mac": "aa:bb:cc:dd:ee:ff", "policy": "vps"},
    ]
    config = Config.model_validate(raw)
    store = DeviceStore(tmp_path / "devices.db")
    store.record(
        [Neighbour("f6:5f:32:9d:fc:41", IPv4Address("192.168.1.2"))], 200.0, lambda _a: None
    )
    body = TestClient(create_app(config, device_store=store)).get("/devices").json()
    assert [(item["name"], item["seen"]) for item in body] == [
        ("phone", True),
        ("printer", False),
        ("old-tv", False),
    ]
    printer = body[1]
    assert (
        printer["mac"] is None and printer["ip"] == "192.168.1.77" and printer["last_seen"] is None
    )
    views = [DeviceView.model_validate(item) for item in body]
    lines = render_devices(views, 300.0)
    assert any(line.startswith("printer") and line.endswith("never seen") for line in lines)
    assert any("old-tv" in line and "aa:bb:cc:dd:ee:ff" in line for line in lines)
