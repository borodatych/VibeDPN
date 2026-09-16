"""Uplink tor: what config.yaml takes, its gateway, the router keys and the bridge file."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from vibedpn import cli
from vibedpn.compose import TOR_BRIDGES_FILE, TOR_CONFIG_DIR, refresh_tor_bridges
from vibedpn.config import DEFAULT_TOR_BRIDGES, Config, Profile, Upstream
from vibedpn.config_edit import set_tor_uplink
from vibedpn.engine.router import (
    UPLINKS,
    router_ruleset,
    smart_marks,
    uplink_service,
    uplink_table,
    used_uplinks,
)

from .conftest import home_config

runner = CliRunner()
BOX_TAIL = (
    "network:\n  lan_interface: eth0\n  lan_subnet: 192.168.1.0/24\n"
    "  lan_address: 192.168.1.50\n"
    "routing:\n  mode: off\n  default_upstream: dpn\n"
    "upstreams:\n  dpn:\n    enabled: true\n"
)


def tor_config(**routing: object) -> Config:
    raw: dict[str, Any] = home_config()
    raw["upstreams"]["tor"] = {"enabled": True}
    if routing:
        raw["routing"] = routing
    return Config.model_validate(raw)


def test_off_by_default_with_the_snowflake_bridges_of_tor_browser() -> None:
    tor = Config.model_validate(home_config()).upstreams.tor
    assert tor.enabled is False
    assert tor.bridges == list(DEFAULT_TOR_BRIDGES)
    assert all(line.startswith("snowflake 192.0.2.") for line in tor.bridges)
    assert Profile.TOR not in Config.model_validate(home_config()).compose_profiles()


def test_enabled_it_starts_its_gateway_profile_and_takes_a_fixed_slot() -> None:
    config = tor_config()
    assert Profile.TOR in config.compose_profiles()
    uplink = uplink_table(config)["tor"]
    assert uplink == UPLINKS[Upstream.TOR]
    assert (uplink.mark, uplink.table, uplink.gateway) == (0x60, 7760, "10.77.0.60")
    assert uplink_service("tor") == "tor"
    # no other slot shares its mark: vps, dpn, block, countries and named exits live below 0x60
    others = {item.mark for key, item in uplink_table(config).items() if key != "tor"}
    assert uplink.mark not in others


def test_bridge_lines_are_checked_for_a_transport_the_image_runs() -> None:
    raw: dict[str, Any] = home_config()
    raw["upstreams"]["tor"] = {
        "enabled": True,
        "bridges": ["  obfs4 203.0.113.9:443 ABCD cert=x  "],
    }
    bridges = Config.model_validate(raw).upstreams.tor.bridges
    assert bridges == ["obfs4 203.0.113.9:443 ABCD cert=x"]
    for bad in ([], ["webtunnel 203.0.113.9:443 url=https://x"], ["snowflake"], ["a\nb c"]):
        raw["upstreams"]["tor"] = {"enabled": True, "bridges": bad}
        with pytest.raises(ValidationError, match="bridge"):
            Config.model_validate(raw)


def test_full_mode_rules_and_device_policies_need_it_enabled() -> None:
    assert "tor" in used_uplinks(tor_config(mode="full", default_upstream="tor"))
    raw: dict[str, Any] = home_config()
    raw["routing"] = {
        "mode": "smart",
        "default_upstream": "dpn",
        "domains": [{"domain": "rutracker.org", "via": "tor"}],
    }
    with pytest.raises(ValidationError, match="via tor but that uplink is not enabled"):
        Config.model_validate(raw)
    raw["routing"]["domains"] = []
    raw["devices"] = [{"name": "phone", "mac": "aa:bb:cc:dd:ee:01", "policy": "tor"}]
    with pytest.raises(ValidationError, match="policy 'tor' but that uplink is not enabled"):
        Config.model_validate(raw)


def test_a_smart_rule_through_tor_marks_its_set_with_the_tor_mark() -> None:
    config = tor_config(
        mode="smart",
        default_upstream="dpn",
        domains=[{"domain": "rutracker.org", "via": "tor"}, {"domain": "vk.com", "via": "direct"}],
    )
    assert "tor" in used_uplinks(config)
    assert {(item.name, item.mark) for item in smart_marks(config)} == {("smart_tor", "0x60")}
    text = router_ruleset(config) or ""
    assert "@smart_tor" in text and "0x60" in text


def test_a_device_on_policy_tor_gets_its_own_sets_and_mark() -> None:
    raw: dict[str, Any] = home_config()
    raw["upstreams"]["tor"] = {"enabled": True}
    raw["devices"] = [{"name": "phone", "mac": "aa:bb:cc:dd:ee:01", "policy": "tor"}]
    config = Config.model_validate(raw)
    assert "tor" in used_uplinks(config)
    text = router_ruleset(config) or ""
    assert "ether saddr @devices_tor_mac meta mark set 0x60 return" in text


def test_the_bridge_file_is_written_on_every_box(tmp_path: Path) -> None:
    config = Config.model_validate(home_config())  # uplink off: the file is there all the same
    path = refresh_tor_bridges(tmp_path, config)
    assert path == tmp_path / TOR_CONFIG_DIR / TOR_BRIDGES_FILE
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("#")
    assert lines[1:] == list(DEFAULT_TOR_BRIDGES)


def test_enable_and_disable_edit_one_key_and_keep_the_rest(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "version: 1\nrole: home\n# my box\nprovider:\n  enabled: true\n" + BOX_TAIL,
        encoding="utf-8",
    )
    config, changed = set_tor_uplink(config_path, True)
    assert changed and config.upstreams.tor.enabled
    text = config_path.read_text(encoding="utf-8")
    assert "# my box" in text and "  tor:\n    enabled: true\n" in text
    assert set_tor_uplink(config_path, True)[1] is False
    assert set_tor_uplink(config_path, False)[0].upstreams.tor.enabled is False


def test_cli_enable_show_and_disable(tmp_path: Path) -> None:
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    (tmp_path / "config.yaml").write_text(
        "version: 1\nrole: home\nprovider:\n  enabled: true\n" + BOX_TAIL,
        encoding="utf-8",
    )
    enabled = runner.invoke(cli.app, ["tor", "enable", "--dir", str(tmp_path)])
    assert enabled.exit_code == 0, enabled.output
    assert "enabled with 2 bridges" in enabled.output
    shown = runner.invoke(cli.app, ["tor", "show", "--dir", str(tmp_path)])
    assert shown.exit_code == 0, shown.output
    assert "tor  enabled  2 bridges" in shown.output and "snowflake 192.0.2.3:80" in shown.output
    disabled = runner.invoke(cli.app, ["tor", "disable", "--dir", str(tmp_path)])
    assert disabled.exit_code == 0 and "disabled" in disabled.output
