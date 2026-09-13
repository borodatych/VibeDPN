"""dnsmasq of gateway mode: rendered only for a gateway box, DHCP only, AdGuard as DNS."""

from pathlib import Path

from vibedpn.config import Config
from vibedpn.engine.dnsmasq import CONF_FILE, dnsmasq_conf, ensure_dnsmasq

from .conftest import home_config


def gateway_box(**dns: bool) -> Config:
    raw = home_config()
    raw["network"] |= {"mode": "gateway", "wan_interface": "eth1", "dhcp": {"lease": "2h"}}
    if dns:
        raw["dns"] = dns
    return Config.model_validate(raw)


def test_sidecar_box_has_no_dnsmasq(tmp_path: Path) -> None:
    config = Config.model_validate(home_config())
    assert dnsmasq_conf(config) is None
    assert ensure_dnsmasq(config, tmp_path) is None
    assert not (tmp_path / CONF_FILE).exists()


def test_gateway_conf_hands_out_the_pool_with_the_box_as_router() -> None:
    text = dnsmasq_conf(gateway_box(enabled=True))
    assert text is not None
    lines = text.splitlines()
    assert "port=0" in lines and "interface=eth0" in lines and "bind-interfaces" in lines
    assert "dhcp-range=192.168.1.100,192.168.1.249,2h" in lines
    assert "dhcp-option=option:router,192.168.1.50" in lines
    assert "dhcp-option=option:dns-server,192.168.1.50" in lines


def test_without_adguard_dns_server_is_not_announced() -> None:
    text = dnsmasq_conf(gateway_box(enabled=False))
    assert text is not None and "dns-server" not in text


def test_ensure_writes_once(tmp_path: Path) -> None:
    config = gateway_box()
    assert ensure_dnsmasq(config, tmp_path / "conf") is True
    assert ensure_dnsmasq(config, tmp_path / "conf") is False
