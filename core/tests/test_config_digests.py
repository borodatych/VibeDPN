"""Fingerprints of config.yaml in .env: `vibedpn up` recreates what a changed section needs."""

from pathlib import Path
from typing import Any

from vibedpn.bootstrap import read_env
from vibedpn.config import (
    DIGEST_ADGUARD,
    DIGEST_CORE,
    DIGEST_DNSMASQ,
    DIGEST_HOSTAPD,
    DIGEST_SERVICES,
    DIGEST_WG_SERVER,
    Config,
    parse_yaml,
    recreated_services,
)

from .conftest import home_config
from .test_wifi import wifi_box

REPO_ROOT = Path(__file__).resolve().parents[2]  # tests/ -> core/ -> repository root


def changed(before: dict[str, Any], after: dict[str, Any]) -> set[str]:
    """The fingerprints that differ between two configurations."""
    old = Config.model_validate(before).config_digests()
    new = Config.model_validate(after).config_digests()
    return {name for name in old if old[name] != new[name]}


def test_a_new_wifi_name_recreates_core_and_hostapd_only() -> None:
    before = wifi_box()
    after = wifi_box(ssid="Other")
    # the Wi-Fi clients of the box stay on when DNS or DHCP settings change, and the other way round
    assert changed(before, after) == {DIGEST_CORE, DIGEST_HOSTAPD}


def test_a_dns_upstream_recreates_core_and_adguard_but_not_the_access_point() -> None:
    before = wifi_box()
    after = wifi_box()
    after["dns"] = {"upstreams": ["https://dns.quad9.net/dns-query"]}
    assert changed(before, after) == {DIGEST_CORE, DIGEST_ADGUARD}


def test_a_lan_change_reaches_every_service_that_reads_it() -> None:
    before = wifi_box()
    after = wifi_box()
    after["network"]["lan_address"] = "192.168.50.2"
    assert changed(before, after) == {DIGEST_CORE, DIGEST_DNSMASQ, DIGEST_ADGUARD}


def test_what_core_applies_live_recreates_nothing() -> None:
    """Routing, devices and rules go through core's API: no container has to start again."""
    before = home_config()
    after = home_config()
    after["routing"] = {
        "mode": "smart",
        "default_upstream": "dpn",
        "domains": [{"domain": "example.org", "via": "direct"}],
    }
    after["devices"] = [{"name": "tv", "mac": "aa:bb:cc:dd:ee:01", "policy": "bypass"}]
    assert changed(before, after) == set()


def test_the_same_config_gives_the_same_fingerprints_and_all_of_them_reach_env() -> None:
    config = Config.model_validate(wifi_box())
    assert config.config_digests() == Config.model_validate(wifi_box()).config_digests()
    env = config.env_vars()
    assert set(DIGEST_SERVICES) <= set(env)
    assert DIGEST_WG_SERVER in env


def test_up_names_only_services_whose_fingerprint_changed() -> None:
    current = {
        DIGEST_CORE: "b",
        DIGEST_HOSTAPD: "b",
        DIGEST_ADGUARD: "a",
        "VIBEDPN_API_PORT": "4480",
    }
    assert recreated_services(
        {DIGEST_CORE: "a", DIGEST_HOSTAPD: "a", DIGEST_ADGUARD: "a"}, current
    ) == [
        "core",
        "hostapd",
    ]
    # the first start after this change has no fingerprints to compare with: nothing is reported
    assert recreated_services({"VIBEDPN_API_PORT": "4480"}, current) == []


def test_a_box_without_wifi_does_not_claim_to_recreate_hostapd() -> None:
    assert Config.model_validate(home_config()).digest_services() == {"core", "adguard"}
    assert "hostapd" in Config.model_validate(wifi_box()).digest_services()


def test_env_is_read_back_without_its_comments(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "# a comment with = inside\nCOMPOSE_PROFILES=router\n\nVIBEDPN_TAG=next\n", "utf-8"
    )
    assert read_env(env) == {"COMPOSE_PROFILES": "router", "VIBEDPN_TAG": "next"}
    assert read_env(tmp_path / "missing") == {}


def test_every_fingerprinted_service_carries_its_fingerprint_in_compose() -> None:
    """Without the variable in the service's environment Compose never sees the change."""
    compose = parse_yaml((REPO_ROOT / "compose.yaml").read_text(encoding="utf-8"))
    assert isinstance(compose, dict)
    for name, service in DIGEST_SERVICES.items():
        environment = compose["services"][service]["environment"]
        assert environment["VIBEDPN_CONFIG_DIGEST"] == f"${{{name}:-}}", service
