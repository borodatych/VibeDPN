"""Network of a LAN box from the panel: saved for the next start, never applied in place."""

from ipaddress import IPv4Address
from pathlib import Path

from fastapi.testclient import TestClient

from vibedpn.api.app import create_app
from vibedpn.api.state import BoxState
from vibedpn.bootstrap import render_config
from vibedpn.config import Config, DevicePolicy, NetworkMode, Upstream, load_config
from vibedpn.config_edit import DeviceIdent, set_device
from vibedpn.detect import Interface

from .conftest import home_config, vps_config

ETH0 = Interface("eth0", IPv4Address("192.168.1.50"), 24)
WLAN0 = Interface("wlan0", IPv4Address("192.168.50.1"), 24)


def lan_box(
    tmp_path: Path, raw: dict[str, object] | None = None
) -> tuple[TestClient, BoxState, list[Config]]:
    path = tmp_path / "config.yaml"
    text = render_config(Config.model_validate(raw or home_config()))
    path.write_text("# the owner's note\n" + text, encoding="utf-8")
    applied: list[Config] = []

    def apply(config: Config) -> list[Upstream]:
        applied.append(config)
        return []

    state = BoxState(load_config(path), path, apply=apply)
    app = create_app(state.config, state=state, interfaces_source=lambda: (ETH0, [ETH0, WLAN0]))
    return TestClient(app), state, applied


def test_gateway_is_saved_and_waits_for_a_restart(tmp_path: Path) -> None:
    client, state, applied = lan_box(tmp_path)
    before = client.get("/network").json()
    assert before["mode"] == "sidecar" and before["restart_required"] is False
    assert [(i["name"], i["default_route"]) for i in before["interfaces"]] == [
        ("eth0", True),
        ("wlan0", False),
    ]
    answer = client.put("/network", json={"lan_interface": "wlan0"})
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert (body["mode"], body["lan_interface"], body["wan_interface"]) == (
        "gateway",
        "wlan0",
        "eth0",
    )
    assert body["lan_address"] == "192.168.50.1" and body["restart_required"] is True
    saved = load_config(state.path).network
    assert saved is not None and saved.mode is NetworkMode.GATEWAY and saved.dhcp is not None
    assert state.path.read_text(encoding="utf-8").startswith("# the owner's note\n")
    assert applied == []  # nothing applied in place
    assert state.config.network is not None and state.config.network.lan_interface == "eth0"


def test_a_live_edit_after_a_saved_network_keeps_the_running_one(tmp_path: Path) -> None:
    client, state, applied = lan_box(tmp_path)
    client.put("/network", json={"lan_interface": "wlan0"})
    state.edit(
        lambda path: set_device(
            path, DeviceIdent.parse("192.168.1.9"), DevicePolicy.BYPASS, None, "device-9"
        )
    )
    assert applied[-1].network is not None and applied[-1].network.lan_interface == "eth0"
    assert state.restart_required is True
    written = load_config(state.path)
    assert written.network is not None and written.network.lan_interface == "wlan0"
    assert len(written.devices) == 1


def test_back_to_sidecar_clears_the_pending_restart(tmp_path: Path) -> None:
    client, _state, _applied = lan_box(tmp_path)
    client.put("/network", json={"lan_interface": "wlan0"})
    body = client.put("/network", json={"lan_interface": None}).json()
    assert body["mode"] == "sidecar" and body["restart_required"] is False
    assert "dhcp" not in (tmp_path / "config.yaml").read_text(encoding="utf-8")


def test_an_interface_without_an_address_is_refused(tmp_path: Path) -> None:
    client, _state, _applied = lan_box(tmp_path)
    answer = client.put("/network", json={"lan_interface": "eth1"})
    assert answer.status_code == 422 and "eth1 has no IPv4 address" in answer.json()["detail"]


def test_a_vps_has_no_network(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(render_config(Config.model_validate(vps_config())), encoding="utf-8")
    state = BoxState(load_config(path), path, apply=lambda _c: [])
    client = TestClient(
        create_app(state.config, state=state, interfaces_source=lambda: (ETH0, [ETH0]))
    )
    assert client.get("/network").status_code == 404
