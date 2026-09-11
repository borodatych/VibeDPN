"""Schema and role rules of config.yaml."""

from ipaddress import IPv4Address
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from vibedpn.config import (
    Config,
    ConfigError,
    Profile,
    Role,
    load_config,
    normalize_mac,
    parse_port_range,
)


def errors_of(data: dict[str, Any]) -> str:
    with pytest.raises(ValidationError) as excinfo:
        Config.model_validate(data)
    return str(excinfo.value)


def test_home_minimal_is_valid(home: dict[str, Any]) -> None:
    config = Config.model_validate(home)
    assert config.role is Role.HOME
    assert config.dns.enabled and config.ui.enabled
    assert config.api.port == 4480


def test_vps_minimal_is_valid(vps: dict[str, Any]) -> None:
    config = Config.model_validate(vps)
    assert config.wg_server is not None
    assert str(config.wg_server.subnet) == "10.78.0.0/24"
    assert config.wg_server.listen_port == 51820


def test_client_minimal_is_valid(client: dict[str, Any]) -> None:
    config = Config.model_validate(client)
    assert config.upstreams.vps.peer_config == Path("secrets/home.conf")


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("home", ["provider", "consumer", "router", "dns", "ui"]),
        ("vps", ["provider", "wg-server"]),
        ("client", ["wg-client", "router", "dns", "ui"]),
    ],
)
def test_compose_profiles_per_role(
    fixture: str, expected: list[str], request: pytest.FixtureRequest
) -> None:
    config = Config.model_validate(request.getfixturevalue(fixture))
    assert [profile.value for profile in config.compose_profiles()] == expected


def test_compose_profiles_follow_disabled_sections(home: dict[str, Any]) -> None:
    home["provider"] = {"enabled": False}
    home["dns"] = {"enabled": False}
    home["ui"] = {"enabled": False}
    assert Config.model_validate(home).compose_profiles() == [Profile.CONSUMER, Profile.ROUTER]


def test_unknown_key_is_rejected(home: dict[str, Any]) -> None:
    home["routing"]["killswitch"] = True
    assert "extra_forbidden" in errors_of(home)


def test_schema_version_must_be_one(home: dict[str, Any]) -> None:
    home["version"] = 2
    assert "version" in errors_of(home)


def test_home_cannot_enable_vps_uplink(home: dict[str, Any]) -> None:
    home["upstreams"]["vps"] = {"enabled": True, "peer_config": "x.conf"}
    assert "role 'home' has no VPS uplink" in errors_of(home)


def test_home_requires_network_and_routing() -> None:
    message = errors_of({"version": 1, "role": "home"})
    assert "network: required" in message
    assert "routing: required" in message


def test_vps_rejects_lan_sections(vps: dict[str, Any]) -> None:
    vps["ui"] = {"enabled": True}
    vps["devices"] = []
    message = errors_of(vps)
    assert "ui: not part of role 'vps'" in message
    assert "devices: not part of role 'vps'" in message


def test_vps_requires_wg_server_and_provider() -> None:
    message = errors_of({"version": 1, "role": "vps"})
    assert "wg_server: required" in message
    assert "provider.enabled: must be true" in message


def test_client_requires_vps_uplink(client: dict[str, Any]) -> None:
    client["upstreams"] = {"vps": {"enabled": False}, "dpn": {"enabled": True}}
    assert "upstreams.vps.enabled: must be true" in errors_of(client)


def test_client_runs_no_provider(client: dict[str, Any]) -> None:
    client["provider"] = {"enabled": True}
    assert "role 'client' runs no node" in errors_of(client)


def test_vps_uplink_needs_peer_config(client: dict[str, Any]) -> None:
    client["upstreams"]["vps"] = {"enabled": True}
    assert "peer_config is required" in errors_of(client)


def test_default_upstream_must_be_enabled_when_routing(home: dict[str, Any]) -> None:
    home["routing"] = {"mode": "full", "default_upstream": "dpn"}
    home["upstreams"] = {"dpn": {"enabled": False}}
    assert "'dpn' is not an enabled uplink" in errors_of(home)


def test_default_upstream_is_not_checked_in_mode_off(client: dict[str, Any]) -> None:
    client["routing"] = {"mode": "off", "default_upstream": "dpn"}
    assert Config.model_validate(client).upstreams.dpn.enabled is False


def test_device_policy_needs_its_uplink(home: dict[str, Any]) -> None:
    home["devices"] = [{"name": "tv", "mac": "AA-BB-CC-DD-EE-01", "policy": "vps"}]
    assert "'tv' uses policy 'vps'" in errors_of(home)


def test_device_mac_is_normalized(home: dict[str, Any]) -> None:
    home["devices"] = [{"name": "tv", "mac": "AA-BB-CC-DD-EE-01", "policy": "bypass"}]
    assert Config.model_validate(home).devices[0].mac == "aa:bb:cc:dd:ee:01"


def test_device_needs_mac_or_ip(home: dict[str, Any]) -> None:
    home["devices"] = [{"name": "tv", "policy": "block"}]
    assert "needs a mac or an ip" in errors_of(home)


def test_duplicate_devices_are_rejected(home: dict[str, Any]) -> None:
    home["devices"] = [
        {"name": "a", "mac": "aa:bb:cc:dd:ee:01", "ip": "192.168.1.5", "policy": "block"},
        {"name": "b", "mac": "aa:bb:cc:dd:ee:01", "ip": "192.168.1.5", "policy": "bypass"},
    ]
    message = errors_of(home)
    assert "duplicate mac aa:bb:cc:dd:ee:01" in message
    assert "duplicate ip 192.168.1.5" in message
    assert Config.model_validate(home | {"devices": []}).devices == []


def test_device_ip_is_parsed(home: dict[str, Any]) -> None:
    home["devices"] = [{"name": "pc", "ip": "192.168.1.9", "policy": "block"}]
    assert Config.model_validate(home).devices[0].ip == IPv4Address("192.168.1.9")


def test_gateway_mode_needs_wan_interface(home: dict[str, Any]) -> None:
    home["network"]["mode"] = "gateway"
    assert "requires network.wan_interface" in errors_of(home)
    home["network"]["wan_interface"] = "eth0"
    assert "must differ" in errors_of(home)
    home["network"]["wan_interface"] = "eth1"
    assert Config.model_validate(home).network is not None


def test_sidecar_mode_has_no_wan_interface(home: dict[str, Any]) -> None:
    home["network"]["wan_interface"] = "eth1"
    assert "only used with network.mode 'gateway'" in errors_of(home)


def test_lan_subnet_must_be_a_network(home: dict[str, Any]) -> None:
    home["network"]["lan_subnet"] = "192.168.1.5/24"
    assert "lan_subnet" in errors_of(home)


def test_smart_domains_are_normalized(home: dict[str, Any]) -> None:
    home["routing"]["smart_domains"] = [".Netflix.com.", "bbc.co.uk"]
    assert Config.model_validate(home).routing is not None
    assert Config.model_validate(home).routing.smart_domains == ["netflix.com", "bbc.co.uk"]  # type: ignore[union-attr]


def test_smart_domains_reject_garbage_and_duplicates(home: dict[str, Any]) -> None:
    home["routing"]["smart_domains"] = ["not a domain"]
    assert "is not a domain name" in errors_of(home)
    home["routing"]["smart_domains"] = ["a.com", "A.com"]
    assert "has duplicates: a.com" in errors_of(home)


def test_country_is_upper_cased(home: dict[str, Any]) -> None:
    home["upstreams"]["dpn"]["country"] = "no"
    assert Config.model_validate(home).upstreams.dpn.country == "NO"


def test_country_must_be_a_string(home: dict[str, Any]) -> None:
    home["upstreams"]["dpn"]["country"] = False
    assert "is not a country code" in errors_of(home)


def test_country_must_be_two_letters(home: dict[str, Any]) -> None:
    home["upstreams"]["dpn"]["country"] = "DEU"
    assert "ISO 3166-1 alpha-2" in errors_of(home)


def test_provider_port_ranges_must_not_overlap(home: dict[str, Any]) -> None:
    home["provider"] = {
        "enabled": True,
        "p2p_ports": "41920-42075",
        "wireguard_ports": "42000-42100",
    }
    assert "must not overlap" in errors_of(home)


@pytest.mark.parametrize("value", ["1024", "abc", "5000-4000", "0-10", "1-70000"])
def test_bad_port_ranges(value: str) -> None:
    with pytest.raises(ValueError, match="port"):
        parse_port_range(value)


def test_port_range_parses() -> None:
    assert parse_port_range("41920-42075") == (41920, 42075)


def test_wg_server_endpoint_and_subnet(vps: dict[str, Any]) -> None:
    vps["wg_server"] = {"endpoint": "bad host!"}
    assert "is not a hostname" in errors_of(vps)
    vps["wg_server"] = {"endpoint": "203.0.113.7", "subnet": "10.78.0.0/31"}
    assert "too small" in errors_of(vps)
    vps["wg_server"] = {"endpoint": "203.0.113.7", "listen_port": 70000}
    assert "listen_port" in errors_of(vps)


def test_dns_upstreams_must_be_doh(home: dict[str, Any]) -> None:
    home["dns"] = {"upstreams": ["8.8.8.8"]}
    assert "is not a DNS-over-HTTPS URL" in errors_of(home)
    home["dns"] = {"upstreams": []}
    assert "at least one" in errors_of(home)


def test_normalize_mac_rejects_short() -> None:
    with pytest.raises(ValueError, match="MAC"):
        normalize_mac("aa:bb:cc")


def test_load_config_reads_yaml(tmp_path: Path, vps: dict[str, Any]) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "version: 1\nrole: vps\nprovider: {enabled: true}\nwg_server: {endpoint: 203.0.113.7}\n",
        encoding="utf-8",
    )
    assert load_config(path).role is Role.VPS
    assert Config.model_validate(vps).role is Role.VPS


def test_load_config_errors(tmp_path: Path) -> None:
    missing = tmp_path / "none.yaml"
    with pytest.raises(ConfigError, match="not found"):
        load_config(missing)
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("role: [", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(bad_yaml)
    scalar = tmp_path / "scalar.yaml"
    scalar.write_text("just a string", encoding="utf-8")
    with pytest.raises(ConfigError, match="must be a mapping"):
        load_config(scalar)
