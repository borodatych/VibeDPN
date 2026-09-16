"""A site or a list through a named WireGuard exit in routing.mode smart."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from vibedpn.api.app import create_app
from vibedpn.api.state import BoxState
from vibedpn.bootstrap import render_config, wg_uplink_secrets
from vibedpn.compose import render_wg_uplinks
from vibedpn.config import Config, DomainRule
from vibedpn.engine.resolver import channel_set, smart_set_names
from vibedpn.engine.router import smart_marks, used_uplinks

from .conftest import home_config


def smart_box(*rules: dict[str, Any], exits: dict[str, Any] | None = None) -> dict[str, Any]:
    raw: dict[str, Any] = home_config()
    raw["upstreams"]["wg"] = exits if exits is not None else {"proton": {}, "my-vps": {}}
    raw["routing"] = {"mode": "smart", "default_upstream": "dpn", "domains": list(rules)}
    return raw


def test_a_rule_names_its_exit_and_only_via_wg_does() -> None:
    config = Config.model_validate(
        smart_box({"domain": "youtube.com", "via": "wg", "uplink": "proton"})
    )
    assert config.routing is not None
    assert config.routing.domains[0].uplink == "proton"
    with pytest.raises(ValidationError, match="via wg names its exit in uplink"):
        Config.model_validate(smart_box({"domain": "youtube.com", "via": "wg"}))
    with pytest.raises(ValidationError, match="an uplink is only named for via wg"):
        Config.model_validate(
            smart_box({"domain": "youtube.com", "via": "vps", "uplink": "proton"})
        )


def test_the_exit_must_be_configured_and_enabled() -> None:
    with pytest.raises(ValidationError, match="no enabled exit of that name"):
        Config.model_validate(
            smart_box({"domain": "youtube.com", "via": "wg", "uplink": "mullvad"})
        )
    parked = smart_box(
        {"domain": "youtube.com", "via": "wg", "uplink": "proton"},
        exits={"proton": {"enabled": False}},
    )
    with pytest.raises(ValidationError, match="no enabled exit of that name"):
        Config.model_validate(parked)


def test_each_exit_has_a_set_of_its_own_and_its_mark() -> None:
    config = Config.model_validate(
        smart_box(
            {"domain": "youtube.com", "via": "wg", "uplink": "proton"},
            {"domain": "example.org", "via": "wg", "uplink": "my-vps"},
            {"domain": "bank.example", "via": "direct"},
        )
    )
    rule = DomainRule.model_validate({"domain": "example.org", "via": "wg", "uplink": "my-vps"})
    # '-' becomes '_' in the set name; names never hold '_', so two exits never share a set
    assert channel_set(rule) == "smart_wg_my_vps"
    assert smart_set_names(config) == ["smart_direct", "smart_wg_my_vps", "smart_wg_proton"]
    # sorted names: my-vps is exit 0 (mark 0x50), proton exit 1 (mark 0x51)
    assert [(item.name, item.mark) for item in smart_marks(config)] == [
        ("smart_wg_my_vps", "0x50"),
        ("smart_wg_proton", "0x51"),
    ]
    # the router builds a table, a kill switch and a watcher for the exits the rules use
    assert {"wg-proton", "wg-my-vps"} <= set(used_uplinks(config))


def test_a_disabled_exit_keeps_its_number_but_gets_no_container_and_needs_no_file() -> None:
    config = Config.model_validate(smart_box(exits={"alpha": {"enabled": False}, "proton": {}}))
    text = render_wg_uplinks(config)
    assert "wg-proton:" in text
    assert "wg-alpha:" not in text
    # proton stays exit 1 while alpha is parked: the marks of the others do not move
    assert "ipv4_address: 10.77.0.51" in text
    assert wg_uplink_secrets(config) == ["wg-proton.conf"]


def test_a_rule_through_an_exit_travels_through_the_api_into_config_yaml(tmp_path: Path) -> None:
    raw = smart_box()
    path = tmp_path / "config.yaml"
    path.write_text(render_config(Config.model_validate(raw)), encoding="utf-8")
    state = BoxState(Config.model_validate(raw), path, apply=lambda _config: [])
    client = TestClient(create_app(state.config, state=state))

    answer = client.put("/rules/youtube.com", json={"via": "wg", "uplink": "proton"})
    assert answer.status_code == 200, answer.text
    assert (answer.json()["via"], answer.json()["uplink"]) == ("wg", "proton")
    assert "uplink: proton" in path.read_text(encoding="utf-8")

    refused = client.put("/rules/other.org", json={"via": "wg", "uplink": "mullvad"})
    assert refused.status_code == 422
    assert "mullvad" in refused.json()["detail"]

    listed = client.put(
        "/lists", json={"url": "https://example.org/list.txt", "via": "wg", "uplink": "my-vps"}
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["uplink"] == "my-vps"
