"""Device policies at runtime: config.yaml edits, PUT/DELETE /devices, watchers, client and CLI."""

import asyncio
import difflib
from ipaddress import IPv4Address
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from vibedpn import cli
from vibedpn.api import client as core_api
from vibedpn.api.app import create_app
from vibedpn.api.models import DevicePolicyView
from vibedpn.api.state import BoxState
from vibedpn.api.uplink import UplinkWatchers
from vibedpn.bootstrap import render_config
from vibedpn.config import Config, DevicePolicy, Upstream, load_config
from vibedpn.config_edit import (
    ConfigEditError,
    DeviceIdent,
    DeviceNotFoundError,
    set_device,
    unset_device,
)
from vibedpn.engine.devices import DeviceStore, Neighbour
from vibedpn.engine.router import UPLINKS, ExitPlan, RouterError, Uplink

from .conftest import client_config

MAC = "f6:5f:32:9d:fc:41"


def box_file(tmp_path: Path, *, with_dpn: bool = False) -> Path:
    raw = client_config()
    if with_dpn:
        raw["upstreams"]["dpn"] = {"enabled": True}
    path = tmp_path / "config.yaml"
    text = render_config(Config.model_validate(raw))
    path.write_text(
        text.replace("routing:\n", "routing:\n  # owner: keep this\n", 1), encoding="utf-8"
    )
    return path


def test_idents_are_macs_or_addresses() -> None:
    assert DeviceIdent.parse("F6-5F-32-9D-FC-41") == DeviceIdent(MAC, None)
    assert DeviceIdent.parse("192.168.1.9") == DeviceIdent(None, IPv4Address("192.168.1.9"))
    assert DeviceIdent.parse(MAC).default_name() == "device-9dfc41"
    with pytest.raises(ConfigEditError, match="neither a MAC nor an IPv4"):
        DeviceIdent.parse("phone")


def test_set_adds_a_block_entry_and_keeps_the_owner_comment(tmp_path: Path) -> None:
    path = box_file(tmp_path)
    before = path.read_text(encoding="utf-8")
    config, changed = set_device(
        path, DeviceIdent.parse(MAC), DevicePolicy.BYPASS, None, "phone.lan"
    )
    after = path.read_text(encoding="utf-8")
    assert changed and [(d.name, d.mac, d.policy) for d in config.devices] == [
        ("phone.lan", MAC, DevicePolicy.BYPASS)
    ]
    assert "# owner: keep this" in after
    added = [
        line for line in difflib.ndiff(before.splitlines(), after.splitlines()) if line[:1] == "+"
    ]
    assert f"+     mac: {MAC}" in added and "+     policy: bypass" in added
    assert "devices: []" not in after  # a block list, not a flow one


def test_set_updates_in_place_and_unset_removes(tmp_path: Path) -> None:
    path = box_file(tmp_path)
    ident = DeviceIdent.parse("192.168.1.9")
    set_device(path, ident, DevicePolicy.BLOCK, "tv", "device-9")
    config, changed = set_device(path, ident, DevicePolicy.BYPASS, None, "ignored")
    assert changed and [(d.name, d.ip, d.policy) for d in config.devices] == [
        ("tv", IPv4Address("192.168.1.9"), DevicePolicy.BYPASS)
    ]
    assert set_device(path, ident, DevicePolicy.BYPASS, None, "ignored")[1] is False
    config, _ = unset_device(path, ident)
    assert config.devices == []
    with pytest.raises(DeviceNotFoundError):
        unset_device(path, ident)


def test_a_policy_for_a_disabled_uplink_is_refused_unwritten(tmp_path: Path) -> None:
    path = box_file(tmp_path)
    before = path.read_text(encoding="utf-8")
    with pytest.raises(ConfigEditError, match="not changed"):
        set_device(path, DeviceIdent.parse(MAC), DevicePolicy.DPN, None, "x")
    assert path.read_text(encoding="utf-8") == before


def test_watchers_follow_the_uplinks_in_use() -> None:
    started: list[str] = []
    cancelled: list[str] = []
    vps, dpn = UPLINKS[Upstream.VPS], UPLINKS[Upstream.DPN]

    async def watch(key: str, _uplink: Uplink, _report: object) -> None:
        started.append(key)
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(key)

    async def scenario() -> None:
        watchers = UplinkWatchers(ExitPlan.of({"vps": vps}), watch=watch)
        runner = asyncio.ensure_future(watchers.run())
        await asyncio.sleep(0)
        watchers.sync(ExitPlan.of({"vps": vps, "dpn": dpn}))
        await asyncio.sleep(0.01)
        assert watchers.watched() == ["vps", "dpn"]
        watchers.sync(ExitPlan.of({"dpn": dpn}))
        await asyncio.sleep(0.01)
        assert watchers.watched() == ["dpn"]
        # a renumbered country: the same key with another uplink gets a fresh watcher
        watchers.sync(ExitPlan.of({"dpn": vps}))
        await asyncio.sleep(0.01)
        assert watchers.watched() == ["dpn"]
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)

    asyncio.run(scenario())
    assert started == ["vps", "dpn", "dpn"]
    assert cancelled == ["vps", "dpn", "dpn"]


class FakeWatchers:
    def __init__(self) -> None:
        self.synced: list[list[Upstream]] = []

    def sync(self, plan: ExitPlan) -> None:
        self.synced.append([Upstream(key) for key in plan.routed])


def app_for(
    tmp_path: Path, apply: object, *, with_dpn: bool = True
) -> tuple[TestClient, Path, FakeWatchers]:
    path = box_file(tmp_path, with_dpn=with_dpn)
    config = load_config(path)
    store = DeviceStore(tmp_path / "devices.db")
    store.record([Neighbour(MAC, IPv4Address("192.168.1.2"))], 1.0, lambda _a: "phone.lan")
    watchers = FakeWatchers()
    state = BoxState(config, path, apply=apply, watchers=watchers)  # type: ignore[arg-type]
    return TestClient(create_app(config, device_store=store, state=state)), path, watchers


def test_put_applies_without_a_restart_and_delete_undoes(tmp_path: Path) -> None:
    applied: list[list[str]] = []

    def apply(config: Config) -> list[Upstream]:
        applied.append([d.policy.value for d in config.devices])
        return [Upstream.VPS, Upstream.DPN] if config.devices else [Upstream.VPS]

    client, path, watchers = app_for(tmp_path, apply)
    response = client.put(f"/devices/{MAC}", json={"policy": "dpn"})
    assert response.status_code == 200
    assert response.json() == {"name": "phone.lan", "mac": MAC, "ip": None, "policy": "dpn"}
    assert load_config(path).devices[0].policy is DevicePolicy.DPN
    listed = client.get("/devices").json()
    assert listed[0]["policy"] == "dpn"  # the API reads the new configuration at once
    assert client.delete(f"/devices/{MAC}").status_code == 204
    assert load_config(path).devices == []
    assert applied == [["dpn"], []]
    assert watchers.synced == [[Upstream.VPS, Upstream.DPN], [Upstream.VPS]]
    assert client.delete(f"/devices/{MAC}").status_code == 404
    assert client.put("/devices/phone", json={"policy": "bypass"}).status_code == 422


def test_a_refused_router_restores_config_yaml(tmp_path: Path) -> None:
    calls = [0]

    def apply(config: Config) -> list[Upstream]:
        calls[0] += 1
        if config.devices:
            raise RouterError("nft -f - failed: syntax error")
        return [Upstream.VPS]

    client, path, watchers = app_for(tmp_path, apply)
    before = path.read_text(encoding="utf-8")
    response = client.put(f"/devices/{MAC}", json={"policy": "block"})
    assert response.status_code == 503 and "restored" in response.json()["detail"]
    assert path.read_text(encoding="utf-8") == before
    assert calls[0] == 2  # the refused change, then the previous configuration again
    assert watchers.synced == []


def test_client_and_cli_set_and_unset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, str, bytes]] = []

    def core(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.content))
        if request.method == "PUT":
            return httpx.Response(
                200, json={"name": "tv", "mac": None, "ip": "192.168.1.9", "policy": "block"}
            )
        return httpx.Response(204)

    transport = httpx.MockTransport(core)
    view = core_api.set_device(4480, "192.168.1.9", DevicePolicy.BLOCK, "tv", transport=transport)
    assert view == DevicePolicyView(
        name="tv", mac=None, ip=IPv4Address("192.168.1.9"), policy="block"
    )
    core_api.unset_device(4480, "192.168.1.9", transport=transport)
    assert seen[0][:2] == ("PUT", "/devices/192.168.1.9") and b'"name":"tv"' in seen[0][2]
    assert seen[1][:2] == ("DELETE", "/devices/192.168.1.9")

    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    (tmp_path / "config.yaml").write_text(
        render_config(Config.model_validate(client_config())), encoding="utf-8"
    )
    monkeypatch.setattr(core_api, "set_device", lambda _port, _ident, _policy, _name: view)
    monkeypatch.setattr(core_api, "unset_device", lambda _port, _ident: None)
    runner = CliRunner()
    result = runner.invoke(
        cli.app, ["device", "set", "192.168.1.9", "block", "--name", "tv", "--dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert "tv (192.168.1.9): policy block, applied" in result.output
    result = runner.invoke(cli.app, ["device", "unset", "192.168.1.9", "--dir", str(tmp_path)])
    assert result.exit_code == 0 and "follows routing.mode" in result.output
