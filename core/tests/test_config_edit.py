"""Routing edits of config.yaml: one line changes, comments and mode stay, invalid never written."""

import difflib
import os
import stat
from pathlib import Path

import pytest

from vibedpn import config_edit
from vibedpn.bootstrap import render_config
from vibedpn.config import Config, RoutingMode, Upstream
from vibedpn.config_edit import ConfigEditError, set_routing

from .conftest import client_config, home_config, vps_config


def write(tmp_path: Path, raw: dict[str, object], extra_comment: str = "") -> Path:
    text = render_config(Config.model_validate(raw))
    if extra_comment:
        text = text.replace("routing:\n", f"routing:\n  # {extra_comment}\n", 1)
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    path.chmod(0o644)
    return path


def changed_lines(before: str, after: str) -> list[str]:
    return [
        line
        for line in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0)
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    ]


def test_mode_switch_changes_exactly_one_line_and_keeps_comments(tmp_path: Path) -> None:
    path = write(tmp_path, client_config(), "owner: keep full at night")
    before = path.read_text(encoding="utf-8")
    config, changed = set_routing(path, mode=RoutingMode.OFF)
    after = path.read_text(encoding="utf-8")
    assert changed and config.routing is not None and config.routing.mode is RoutingMode.OFF
    assert changed_lines(before, after) == ["-  mode: full", "+  mode: off"]
    assert "# owner: keep full at night" in after
    assert stat.S_IMODE(path.stat().st_mode) == 0o644


def test_the_same_value_writes_nothing(tmp_path: Path) -> None:
    path = write(tmp_path, client_config())
    stamp = path.stat().st_mtime_ns
    _, changed = set_routing(path, mode=RoutingMode.FULL)
    assert not changed and path.stat().st_mtime_ns == stamp


def test_an_invalid_result_is_refused_before_writing(tmp_path: Path) -> None:
    """home runs only dpn: full through vps would be a box core refuses to start."""
    raw = home_config()
    path = write(tmp_path, raw)
    before = path.read_text(encoding="utf-8")
    with pytest.raises(ConfigEditError, match=r"config\.yaml not changed: .*vps"):
        set_routing(path, mode=RoutingMode.FULL, upstream=Upstream.VPS)
    assert path.read_text(encoding="utf-8") == before


def test_a_box_without_routing_is_refused(tmp_path: Path) -> None:
    path = write(tmp_path, vps_config())
    with pytest.raises(ConfigEditError, match="no routing section"):
        set_routing(path, mode=RoutingMode.FULL)


def test_a_root_owned_directory_asks_for_sudo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write(tmp_path, client_config())

    def refuse(_path: Path, _content: str) -> bool:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(config_edit, "write_like", refuse)
    with pytest.raises(ConfigEditError, match="run with sudo"):
        set_routing(path, mode=RoutingMode.OFF)


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes anywhere")
def test_write_like_really_needs_a_writable_directory(tmp_path: Path) -> None:
    path = write(tmp_path, client_config())
    tmp_path.chmod(0o555)
    try:
        with pytest.raises(ConfigEditError, match="run with sudo"):
            set_routing(path, mode=RoutingMode.OFF)
    finally:
        tmp_path.chmod(0o755)
