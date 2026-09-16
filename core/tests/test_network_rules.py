"""routing.networks: address networks in smart mode — config, router sets, edits, API and CLI."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from vibedpn.api.app import create_app
from vibedpn.api.state import BoxState
from vibedpn.bootstrap import render_config
from vibedpn.config import Config, NetworkRule, Upstream, load_config, parse_yaml
from vibedpn.config_edit import NetworkRuleNotFoundError, remove_network_rule, set_network_rule
from vibedpn.engine.router import router_ruleset, smart_networks, used_uplinks

from .conftest import home_config

# The IPv4 networks Telegram publishes (https://core.telegram.org/resources/cidr.txt, 2026-09-17).
TELEGRAM = ["149.154.160.0/20", "91.108.4.0/22", "91.108.56.0/22", "91.105.192.0/23"]


def smart_box(networks: list[dict[str, Any]], **extra: object) -> dict[str, Any]:
    raw: dict[str, Any] = home_config()
    raw["upstreams"]["tor"] = {"enabled": True}
    raw["routing"] = {"mode": "smart", "default_upstream": "dpn", "networks": networks, **extra}
    return raw


def test_a_network_takes_a_channel_and_its_uplink_is_used() -> None:
    config = Config.model_validate(smart_box([{"network": net, "via": "tor"} for net in TELEGRAM]))
    assert config.routing is not None
    assert [str(rule.network) for rule in config.routing.networks] == TELEGRAM
    assert "tor" in used_uplinks(config)
    (only,) = smart_networks(config)
    assert only.name == "smart_tor_net" and only.mark == "0x60"
    assert only.elements == sorted(TELEGRAM)


@pytest.mark.parametrize(
    ("networks", "message"),
    [
        ([{"network": "149.154.167.51/20", "via": "tor"}], "not an IPv4 network"),
        ([{"network": "2001:b28:f23d::/48", "via": "tor"}], "not an IPv4 network"),
        ([{"network": "149.154.160.0/20", "via": "tor"}] * 2, "listed twice"),
        ([{"network": "149.154.160.0/20", "via": "vps"}], "via vps but that uplink is not enabled"),
        ([{"network": "149.154.160.0/20", "via": "wg"}], "names its exit in uplink"),
    ],
)
def test_a_wrong_network_is_refused_with_its_reason(
    networks: list[dict[str, Any]], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        Config.model_validate(smart_box(networks))


def test_direct_networks_come_first_and_the_ruleset_carries_the_elements() -> None:
    config = Config.model_validate(
        smart_box(
            [
                {"network": "149.154.160.0/20", "via": "tor"},
                {"network": "149.154.167.0/24", "via": "direct"},
            ]
        )
    )
    names = [item.name for item in smart_networks(config)]
    assert names == ["smart_direct_net", "smart_tor_net"]
    text = router_ruleset(config) or ""
    assert "set smart_tor_net {" in text and "elements = { 149.154.160.0/20 }" in text
    assert "flags interval" in text
    direct = text.index("ip daddr @smart_direct_net return")
    tor = text.index("ip daddr @smart_tor_net meta mark set 0x60 return")
    assert direct < tor


def test_outside_smart_mode_no_network_set_is_built() -> None:
    raw = smart_box([{"network": "149.154.160.0/20", "via": "tor"}])
    raw["routing"]["mode"] = "off"
    config = Config.model_validate(raw)
    assert smart_networks(config) == []
    assert "smart_tor_net" not in (router_ruleset(config) or "")


def test_networks_are_added_replaced_and_removed_in_config_yaml(tmp_path: Path) -> None:
    raw = home_config()
    raw["upstreams"]["tor"] = {"enabled": True}
    path = tmp_path / "config.yaml"
    path.write_text(render_config(Config.model_validate(raw)), encoding="utf-8")
    rule = NetworkRule.model_validate({"network": "149.154.160.0/20", "via": "tor"})
    config, _ = set_network_rule(path, rule)
    replaced = NetworkRule.model_validate({"network": "149.154.160.0/20", "via": "direct"})
    config, _ = set_network_rule(path, replaced)
    assert config.routing is not None and config.routing.networks == [replaced]
    assert load_config(path).routing == config.routing
    config, _ = remove_network_rule(path, "149.154.160.0/20")
    assert config.routing is not None and config.routing.networks == []
    with pytest.raises(NetworkRuleNotFoundError):
        remove_network_rule(path, "149.154.160.0/20")


def test_the_rendered_config_keeps_its_networks() -> None:
    config = Config.model_validate(smart_box([{"network": "91.108.4.0/22", "via": "tor"}]))
    assert Config.model_validate(parse_yaml(render_config(config))).routing == config.routing


def test_the_api_lists_puts_and_deletes_a_network_and_applies_it(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(render_config(Config.model_validate(smart_box([]))), encoding="utf-8")
    applied: list[Config] = []

    def apply(config: Config) -> list[Upstream]:
        applied.append(config)
        return []

    state = BoxState(load_config(path), path, apply=apply)
    client = TestClient(create_app(state.config, state=state))
    put = client.put("/networks", json={"network": "149.154.160.0/20", "via": "tor"})
    assert put.status_code == 200, put.text
    assert put.json() == {
        "network": "149.154.160.0/20",
        "via": "tor",
        "country": None,
        "uplink": None,
    }
    assert applied and applied[-1].routing is not None
    assert [str(rule.network) for rule in applied[-1].routing.networks] == ["149.154.160.0/20"]
    assert client.get("/networks").json()[0]["network"] == "149.154.160.0/20"
    bad = client.put("/networks", json={"network": "149.154.167.51/20", "via": "tor"})
    assert bad.status_code == 422
    assert client.delete("/networks", params={"network": "149.154.160.0/20"}).status_code == 204
    assert client.delete("/networks", params={"network": "149.154.160.0/20"}).status_code == 404
