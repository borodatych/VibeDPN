"""Fingerprints of config.yaml in .env: `vibedpn up` recreates what a changed section needs."""

import types
import typing
from collections.abc import Callable
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from vibedpn.bootstrap import read_env
from vibedpn.compose import DIGEST_WG_CLIENT, DIGEST_XRAY
from vibedpn.config import (
    DIGEST_ADGUARD,
    DIGEST_CORE,
    DIGEST_DNSMASQ,
    DIGEST_HOSTAPD,
    DIGEST_SERVICES,
    DIGEST_TOR,
    DIGEST_WG_SERVER,
    Config,
    DeviceConfig,
    DevicePolicy,
    DomainList,
    DomainRule,
    DomainVia,
    NetworkRule,
    Role,
    RoutingMode,
    Traversal,
    UiVariant,
    parse_yaml,
    recreated_services,
)

from .conftest import client_config, home_config, vps_config
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
    carried = {**DIGEST_SERVICES, DIGEST_XRAY: "xray", DIGEST_WG_CLIENT: "wg-client"}
    for name, service in carried.items():
        environment = compose["services"][service]["environment"]
        assert environment["VIBEDPN_CONFIG_DIGEST"] == f"${{{name}:-}}", service


# --- every field of config.yaml reaches the service that reads it -------------------------------
#
# core keeps the config it started with; `vibedpn up` recreates a service only when its
# fingerprint changes (decision 25). So each field has exactly one of these ways to take effect,
# and a field nobody sorted is a change `up` could lose without a word.

CORE = "core"  # core reads it at start, or only an edit of the file changes it: core's fingerprint
LIVE = "live"  # core applies it live through its API: no fingerprint moves, nothing restarts
ENV = "env"  # another service reads it: its environment or fingerprint changes, core's does not
NOBODY = "nobody"

# A path covers every field under it; a whole section is listed only where its model_dump is in
# the fingerprint, so a field added to it later is carried by construction.
REACH = {
    "version": NOBODY,
    "role": CORE,
    "network": CORE,
    "routing.mode": LIVE,
    "routing.default_upstream": LIVE,
    "routing.failopen": CORE,
    "routing.domains": LIVE,
    "routing.lists": LIVE,
    "routing.networks": LIVE,
    "devices": LIVE,
    "upstreams.vps.enabled": CORE,
    "upstreams.vps.lan_access": LIVE,
    "upstreams.dpn.enabled": CORE,
    "upstreams.dpn.country": LIVE,
    "upstreams.tor.enabled": CORE,
    "upstreams.tor.bridges": ENV,
    "upstreams.xray.enabled": CORE,
    "upstreams.wg.*.enabled": CORE,
    "provider.enabled": CORE,
    "provider.udp_ports": CORE,
    "provider.traversal": ENV,
    "wg_server": CORE,
    "dns": CORE,
    "ui.enabled": CORE,
    "ui.port": CORE,
    "ui.variant": ENV,
    "ui.host_name": CORE,
    "ui.language": CORE,  # the panel reads it from its environment, the Telegram bot of core too
    "api": CORE,
    "firewall": CORE,
    "access.enabled": CORE,
    "access.address": CORE,
    "access.port": CORE,
    "access.target": CORE,
    "ddns": CORE,
    "telegram": CORE,
}


def _nested_model(annotation: object) -> type[BaseModel] | None:
    """The section model of a field — itself or behind ``| None`` — to walk into."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    if isinstance(annotation, types.UnionType) or typing.get_origin(annotation) is typing.Union:
        models = [item for item in typing.get_args(annotation) if item is not type(None)]
        if len(models) == 1:
            return _nested_model(models[0])
    return None


def field_paths(model: type[BaseModel], prefix: str = "") -> list[str]:
    """Every field of config.yaml as a dotted path; ``*`` stands for a key the owner names."""
    paths: list[str] = []
    for name, field in model.model_fields.items():
        path = f"{prefix}{name}"
        section = _nested_model(field.annotation)
        if section is not None:
            paths += field_paths(section, f"{path}.")
        elif typing.get_origin(field.annotation) is dict:
            item = _nested_model(typing.get_args(field.annotation)[1])
            paths += field_paths(item, f"{path}.*.") if item is not None else [path]
        else:
            paths.append(path)
    return paths


def reach_of(path: str) -> str | None:
    parts = path.split(".")
    for end in range(len(parts), 0, -1):
        reach = REACH.get(".".join(parts[:end]))
        if reach is not None:
            return reach
    return None


def test_every_field_of_config_yaml_is_sorted() -> None:
    paths = field_paths(Config)
    assert [path for path in paths if reach_of(path) is None] == [], (
        "a new field of config.yaml: add it to REACH, and to the fingerprint of whoever reads it"
    )
    covered = [key for key in REACH if not any(p == key or p.startswith(f"{key}.") for p in paths)]
    assert covered == [], "REACH names fields config.yaml no longer has"


def _replaced(node: object, path: str, value: object) -> object:
    head, _, rest = path.partition(".")
    if isinstance(node, dict):
        return {**node, head: _replaced(node[head], rest, value) if rest else value}
    assert isinstance(node, BaseModel)
    inner = _replaced(getattr(node, head), rest, value) if rest else value
    return node.model_copy(update={head: inner})


def with_value(config: Config, path: str, value: object) -> Config:
    """A copy with one field changed, validation aside: the fingerprint is what is under test."""
    changed_config = _replaced(config, path, value)
    assert isinstance(changed_config, Config)
    return changed_config


def rich_home() -> Config:
    """A home box using everything a home box can: every live field has something to change."""
    data = home_config()
    data["routing"] = {
        "mode": "smart",
        "default_upstream": "dpn",
        "domains": [{"domain": "example.org", "via": "tor"}],
        "networks": [{"network": "198.51.100.0/24", "via": "direct"}],
        "lists": [{"url": "https://lists.example.org/a.txt", "via": "tor"}],
    }
    data["upstreams"] = {
        "dpn": {"enabled": True},
        "tor": {"enabled": True},
        "xray": {"enabled": True},
        "wg": {"work": {"enabled": True}},
    }
    data["devices"] = [{"name": "tv", "mac": "aa:bb:cc:dd:ee:01", "policy": "bypass"}]
    data["access"] = {"enabled": True, "address": "home.example.org"}
    data["ddns"] = {"enabled": True}
    return Config.model_validate(data)


def rich_vps() -> Config:
    data = vps_config()
    data["ui"] = {"enabled": True}
    return Config.model_validate(data)


def rich_client() -> Config:
    return Config.model_validate(client_config())


Box = Callable[[], Config]
# the change each field is checked with, on a box where the field means something
CHANGES: dict[str, tuple[Box, str, object]] = {
    "role": (rich_home, "role", Role.CLIENT),
    "network": (rich_home, "network.lan_address", IPv4Address("192.168.1.51")),
    "routing.mode": (rich_home, "routing.mode", RoutingMode.FULL),
    "routing.default_upstream": (rich_home, "routing.default_upstream", "tor"),
    "routing.failopen": (rich_home, "routing.failopen", True),
    "routing.domains": (
        rich_home,
        "routing.domains",
        [DomainRule(domain="example.net", via=DomainVia.TOR)],
    ),
    "routing.lists": (
        rich_home,
        "routing.lists",
        [DomainList(url="https://lists.example.org/b.txt", via=DomainVia.TOR)],
    ),
    "routing.networks": (
        rich_home,
        "routing.networks",
        [NetworkRule(network=IPv4Network("203.0.113.0/24"), via=DomainVia.TOR)],
    ),
    "devices": (
        rich_home,
        "devices",
        [DeviceConfig(name="tv", mac="aa:bb:cc:dd:ee:01", policy=DevicePolicy.TOR)],
    ),
    "upstreams.vps.enabled": (rich_client, "upstreams.vps.enabled", False),
    "upstreams.vps.lan_access": (rich_client, "upstreams.vps.lan_access", True),
    "upstreams.dpn.enabled": (rich_home, "upstreams.dpn.enabled", False),
    "upstreams.dpn.country": (rich_home, "upstreams.dpn.country", "DE"),
    "upstreams.tor.enabled": (rich_home, "upstreams.tor.enabled", False),
    "upstreams.tor.bridges": (rich_home, "upstreams.tor.bridges", ["obfs4 192.0.2.9:443 X"]),
    "upstreams.xray.enabled": (rich_home, "upstreams.xray.enabled", False),
    "upstreams.wg.*.enabled": (rich_home, "upstreams.wg.work.enabled", False),
    "provider.enabled": (rich_home, "provider.enabled", False),
    "provider.udp_ports": (rich_vps, "provider.udp_ports", "57000-57100"),
    "provider.traversal": (rich_home, "provider.traversal", [Traversal.UPNP]),
    "wg_server": (rich_vps, "wg_server.listen_port", 51821),
    "dns": (rich_home, "dns.enabled", False),
    "ui.enabled": (rich_home, "ui.enabled", False),
    "ui.port": (rich_vps, "ui.port", 8080),
    "ui.variant": (rich_home, "ui.variant", UiVariant.LITE),
    "ui.host_name": (rich_home, "ui.host_name", "box.lan"),
    "ui.language": (rich_home, "ui.language", "en"),
    "api": (rich_home, "api.port", 4490),
    "firewall": (rich_vps, "firewall.ssh_ports", [22, 2222]),
    "access.enabled": (rich_home, "access.enabled", False),
    "access.address": (rich_home, "access.address", "other.example.org"),
    "access.port": (rich_home, "access.port", 8443),
    "access.target": (rich_home, "access.target", "www.apple.com"),
    "ddns": (rich_home, "ddns.enabled", False),
    "telegram": (rich_home, "telegram.alert_after_seconds", 120),
}


def test_every_sorted_field_has_a_change_to_check_it_with() -> None:
    assert set(CHANGES) == {key for key, reach in REACH.items() if reach != NOBODY}


@pytest.mark.parametrize("key", sorted(CHANGES))
def test_a_change_of_a_field_reaches_whoever_reads_it(key: str) -> None:
    box, path, value = CHANGES[key]
    before = box()
    after = with_value(before, path, value)
    assert getattr(after, path.split(".")[0]) != getattr(before, path.split(".")[0])  # it changed
    old, new = before.config_digests(), after.config_digests()
    reach = REACH[key]
    if reach == CORE:
        assert new[DIGEST_CORE] != old[DIGEST_CORE], f"{key}: core would keep the old value"
    elif reach == LIVE:
        assert new == old, f"{key}: applied live, yet `up` would recreate a service for it"
    else:
        assert new[DIGEST_CORE] == old[DIGEST_CORE], f"{key}: core does not read it"
        assert after.env_vars() != before.env_vars(), f"{key}: its service would not notice"


def test_new_bridges_recreate_tor_and_nothing_else() -> None:
    before = rich_home()
    after = with_value(before, "upstreams.tor.bridges", ["obfs4 192.0.2.9:443 X"])
    old, new = before.config_digests(), after.config_digests()
    assert {name for name in old if old[name] != new[name]} == {DIGEST_TOR}
