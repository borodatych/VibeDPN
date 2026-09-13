"""vibedpn mode / upstream: config.yaml edited in place, only core restarted when it runs."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from vibedpn import cli
from vibedpn.bootstrap import render_config
from vibedpn.config import Config, RoutingMode, Upstream, load_config

from .conftest import client_config, vps_config
from .test_cli_compose import Recorder, tail

runner = CliRunner()
CORE_RUNNING = '{"Service":"core","State":"running","Health":"healthy","Status":"Up"}\n'


def make_box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: dict[str, object]) -> Recorder:
    recorder = Recorder()
    monkeypatch.setattr(cli, "run", recorder.run)
    monkeypatch.setattr(cli, "capture", recorder.capture)
    monkeypatch.setattr(cli, "preflight", lambda: None)
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    config = Config.model_validate(raw)
    (tmp_path / "config.yaml").write_text(render_config(config), encoding="utf-8")
    return recorder


def invoke(tmp_path: Path, *args: str) -> tuple[int, str]:
    result = runner.invoke(cli.app, [*args, "--dir", str(tmp_path)])
    return result.exit_code, result.output


def test_mode_restarts_only_core_when_it_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = make_box(tmp_path, monkeypatch, client_config())
    recorder.ps_output = CORE_RUNNING
    code, output = invoke(tmp_path, "mode", "off")
    assert code == 0, output
    assert (
        "routing: mode=off default_upstream=vps failopen=false (applied: core restarted)" in output
    )
    assert [tail(argv) for argv in recorder.calls if "restart" in argv] == [
        ["restart", "--no-deps", "core"]
    ]
    routing = load_config(tmp_path / "config.yaml").routing
    assert routing is not None and routing.mode is RoutingMode.OFF


def test_mode_on_a_stopped_box_only_saves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = make_box(tmp_path, monkeypatch, client_config())
    code, output = invoke(tmp_path, "mode", "off")
    assert code == 0 and "(saved; applies at `vibedpn up`)" in output
    assert not [argv for argv in recorder.calls if "restart" in argv]


def test_the_same_mode_touches_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = make_box(tmp_path, monkeypatch, client_config())
    code, output = invoke(tmp_path, "mode", "full")
    assert code == 0 and "(already set)" in output
    assert recorder.calls == []


def test_smart_is_not_offered_yet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_box(tmp_path, monkeypatch, client_config())
    code, _ = invoke(tmp_path, "mode", "smart")
    assert code == 2  # rejected by the argument parser, before config.yaml is read


def test_a_vps_has_no_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_box(tmp_path, monkeypatch, vps_config())
    code, output = invoke(tmp_path, "mode", "full")
    assert code == 1 and "no routing section" in output


def test_upstream_to_a_disabled_uplink_is_refused_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = make_box(tmp_path, monkeypatch, client_config())
    before = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    code, output = invoke(tmp_path, "upstream", "dpn")
    assert code == 1 and "config.yaml not changed" in output and "dpn" in output
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == before
    assert recorder.calls == []
    routing = load_config(tmp_path / "config.yaml").routing
    assert routing is not None and routing.default_upstream is Upstream.VPS
