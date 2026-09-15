"""Named WireGuard exits in config.yaml: added, disabled, removed, and never left inconsistent."""

from pathlib import Path
from typing import Any

import pytest

from vibedpn.bootstrap import render_config
from vibedpn.config import Config
from vibedpn.config_edit import (
    ConfigEditError,
    WgUplinkNotFoundError,
    remove_wg_uplink,
    set_wg_uplink,
)

from .conftest import home_config


def write(tmp_path: Path, raw: dict[str, Any]) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(render_config(Config.model_validate(raw)), encoding="utf-8")
    path.chmod(0o644)
    return path


def box_with(*names: str, default_upstream: str = "dpn") -> dict[str, Any]:
    raw: dict[str, Any] = home_config()
    raw["upstreams"]["wg"] = {name: {"enabled": True} for name in names}
    raw["routing"] = {"mode": "full", "default_upstream": default_upstream}
    return raw


def test_a_name_is_added_and_then_disabled_without_losing_it(tmp_path: Path) -> None:
    path = write(tmp_path, home_config())
    config, changed = set_wg_uplink(path, "proton")
    assert changed and config.upstreams.wg["proton"].enabled
    config, changed = set_wg_uplink(path, "proton", enabled=False)
    # still configured, just not started: the file in secrets/ keeps its meaning
    assert changed and not config.upstreams.wg["proton"].enabled
    assert "proton" in path.read_text(encoding="utf-8")


def test_a_second_write_of_the_same_state_changes_nothing(tmp_path: Path) -> None:
    path = write(tmp_path, box_with("proton"))
    before = path.read_text(encoding="utf-8")
    _config, changed = set_wg_uplink(path, "proton")
    assert not changed and path.read_text(encoding="utf-8") == before


def test_removing_a_name_drops_it_and_an_unknown_one_says_so(tmp_path: Path) -> None:
    path = write(tmp_path, box_with("proton", "mullvad"))
    config, changed = remove_wg_uplink(path, "mullvad")
    assert changed and set(config.upstreams.wg) == {"proton"}
    with pytest.raises(WgUplinkNotFoundError, match="no WireGuard exit named 'mullvad'"):
        remove_wg_uplink(path, "mullvad")


def test_the_exit_the_lan_goes_through_cannot_be_removed(tmp_path: Path) -> None:
    """Removing it would leave routing.mode full pointing at an uplink the box does not run."""
    path = write(tmp_path, box_with("proton", default_upstream="wg-proton"))
    before = path.read_text(encoding="utf-8")
    with pytest.raises(ConfigEditError, match="not an enabled uplink"):
        remove_wg_uplink(path, "proton")
    assert path.read_text(encoding="utf-8") == before
