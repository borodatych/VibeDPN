"""Wi-Fi access point of gateway mode: the config section, hostapd.conf, doctor, the network API."""

import stat
from ipaddress import IPv4Address
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from vibedpn.api.app import create_app
from vibedpn.api.state import BoxState
from vibedpn.bootstrap import render_config
from vibedpn.config import Config, Profile, load_config, parse_yaml
from vibedpn.detect import Interface, is_wireless
from vibedpn.doctor import Verdict, evaluate
from vibedpn.engine.hostapd import (
    CONF_FILE,
    PASSPHRASE_FILE,
    HostapdError,
    ensure_hostapd,
    hostapd_conf,
)

from .conftest import home_config
from .test_doctor import facts

WAN = Interface("eth0", IPv4Address("192.168.1.50"), 24)
RADIO = Interface("wlan0", IPv4Address("192.168.50.1"), 24)


def wifi_box(**wifi: str | int) -> dict[str, Any]:
    raw = home_config()
    raw["network"] = {
        "mode": "gateway",
        "lan_interface": "wlan0",
        "lan_subnet": "192.168.50.0/24",
        "lan_address": "192.168.50.1",
        "wan_interface": "eth0",
        "wifi": {"ssid": "Home", "country": "de", **wifi},
    }
    return raw


def errors(raw: dict[str, Any]) -> str:
    with pytest.raises(ValueError, match=r"network") as caught:
        Config.model_validate(raw)
    return str(caught.value)


def test_wifi_section_is_checked() -> None:
    config = Config.model_validate(wifi_box())
    assert config.network is not None and config.network.wifi is not None
    assert config.network.wifi.country == "DE"
    assert Profile.WIFI in config.compose_profiles()
    assert "channel 36 is not in band 2.4 GHz" in errors(wifi_box(channel=36))
    assert "is not an SSID" in errors(wifi_box(ssid="x" * 33))
    assert "not an ISO 3166-1" in errors(wifi_box(country="Germany"))
    sidecar = wifi_box()
    sidecar["network"] |= {"mode": "sidecar"}
    del sidecar["network"]["wan_interface"]
    assert "network.wifi is only used" in errors(sidecar)


def test_the_section_survives_config_yaml() -> None:
    raw = wifi_box(band="5", channel=36, ssid='Дом "5"', security="wpa3")
    config = Config.model_validate(raw)
    loaded = parse_yaml(render_config(config))
    assert isinstance(loaded, dict)
    again = Config.model_validate(loaded)
    assert again.network is not None and config.network is not None
    assert again.network.wifi == config.network.wifi


def test_hostapd_conf_per_security() -> None:
    transition = hostapd_conf(Config.model_validate(wifi_box()), "pass-phrase-1")
    assert transition is not None
    lines = transition.splitlines()
    assert "interface=wlan0" in lines and "ssid=Home" in lines and "country_code=DE" in lines
    assert "hw_mode=g" in lines and "channel=6" in lines
    assert "wpa_key_mgmt=WPA-PSK SAE" in lines and "ieee80211w=1" in lines
    assert "wpa_passphrase=pass-phrase-1" in lines
    wpa3_box = Config.model_validate(wifi_box(security="wpa3", band="5", channel=36))
    wpa3 = hostapd_conf(wpa3_box, "pass-phrase-1")
    assert wpa3 is not None
    assert "wpa_key_mgmt=SAE" in wpa3 and "ieee80211w=2" in wpa3 and "hw_mode=a" in wpa3
    assert hostapd_conf(Config.model_validate(home_config()), "pass-phrase-1") is None


def test_ensure_writes_the_passphrase_privately(tmp_path: Path) -> None:
    config = Config.model_validate(wifi_box())
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    with pytest.raises(HostapdError, match=r"init --force"):
        ensure_hostapd(config, tmp_path / "conf", secrets)
    (secrets / PASSPHRASE_FILE).write_text("pass-phrase-1\n", encoding="utf-8")
    assert ensure_hostapd(config, tmp_path / "conf", secrets) is True
    assert ensure_hostapd(config, tmp_path / "conf", secrets) is False
    written = tmp_path / "conf" / CONF_FILE
    assert stat.S_IMODE(written.stat().st_mode) == 0o600
    assert ensure_hostapd(Config.model_validate(home_config()), tmp_path / "x", secrets) is None


def test_a_radio_is_told_by_sysfs(tmp_path: Path) -> None:
    (tmp_path / "wlan0" / "wireless").mkdir(parents=True)
    (tmp_path / "eth0").mkdir()
    assert is_wireless("wlan0", tmp_path) is True
    assert is_wireless("eth0", tmp_path) is False
    assert is_wireless("../wlan0", tmp_path) is False


def test_doctor_wants_the_radio_as_lan() -> None:
    config = Config.model_validate(wifi_box())
    failing = evaluate(facts(config=config, lan_address_set=True, lan_wireless=False))
    assert any(r.name == "wifi" and r.verdict is Verdict.FAIL for r in failing)
    passing = evaluate(facts(config=config, lan_address_set=True, lan_wireless=True))
    assert any(r.name == "wifi" and r.verdict is Verdict.OK for r in passing)


def test_network_api_keeps_wifi_and_refuses_to_move_its_lan(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(render_config(Config.model_validate(wifi_box())), encoding="utf-8")
    state = BoxState(load_config(path), path, apply=lambda _config: [])
    other = Interface("eth1", IPv4Address("10.9.0.1"), 24)
    detected = (WAN, [WAN, RADIO, other])
    app = create_app(state.config, state=state, interfaces_source=lambda: detected)
    client = TestClient(app)
    kept = client.put("/network", json={"lan_interface": "wlan0"})
    assert kept.status_code == 200, kept.text
    network = load_config(path).network
    assert network is not None and network.wifi is not None and network.wifi.ssid == "Home"
    moved = client.put("/network", json={"lan_interface": "eth1"})
    assert moved.status_code == 422 and "access point is on wlan0" in moved.json()["detail"]
