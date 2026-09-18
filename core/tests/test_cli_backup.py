"""vibedpn backup / restore / update with Compose, git and systemctl recorded, not run."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vibedpn import cli
from vibedpn.bootstrap import render_config
from vibedpn.config import Config

from .conftest import home_config
from .test_cli_compose import Recorder

runner = CliRunner()


def make_box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Recorder:
    recorder = Recorder()
    monkeypatch.setattr(cli, "run", recorder.run)
    monkeypatch.setattr(cli, "capture", recorder.capture)
    monkeypatch.setattr(cli, "preflight", lambda: None)
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    (tmp_path / "config.yaml").write_text(
        render_config(Config.model_validate(home_config())), encoding="utf-8"
    )
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "htpasswd").write_text("admin:x\n", encoding="utf-8")
    return recorder


def verbs(recorder: Recorder) -> list[str]:
    return [" ".join(call[-3:]) for call in recorder.calls]


def test_backup_stops_a_running_box_and_brings_it_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = make_box(tmp_path, monkeypatch)
    recorder.ps_output = json.dumps({"Service": "core", "State": "running", "Health": "healthy"})
    out = tmp_path / "copy.tar.gz"
    result = runner.invoke(cli.app, ["backup", "--out", str(out), "--dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert out.is_file() and "keep it private" in result.output
    joined = verbs(recorder)
    assert any(call.endswith("stop") for call in joined)
    assert joined[-1].endswith("up -d")


def test_backup_of_a_stopped_box_starts_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = make_box(tmp_path, monkeypatch)
    result = runner.invoke(cli.app, ["backup", "--dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert list((tmp_path / "backups").glob("vibedpn-*.tar.gz"))
    assert not any("up" in call or "stop" in call for call in verbs(recorder))


def test_restore_takes_the_box_down_and_keeps_the_old_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_box(tmp_path, monkeypatch)
    out = tmp_path / "copy.tar.gz"
    assert (
        runner.invoke(cli.app, ["backup", "--out", str(out), "--dir", str(tmp_path)]).exit_code == 0
    )
    (tmp_path / "secrets" / "htpasswd").write_text("admin:changed\n", encoding="utf-8")
    result = runner.invoke(cli.app, ["restore", str(out), "--dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "secrets" / "htpasswd").read_text(encoding="utf-8") == "admin:x\n"
    assert "previous files are in" in result.output


def test_update_needs_a_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_box(tmp_path, monkeypatch)
    result = runner.invoke(cli.app, ["update", "--dir", str(tmp_path)])
    assert result.exit_code == 1 and "not a checkout" in result.output


def test_update_runs_install_sh_pull_and_the_new_cli_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = make_box(tmp_path, monkeypatch)
    (tmp_path / ".git").mkdir()
    (tmp_path / "install.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    recorder.ps_output = "next\n"
    result = runner.invoke(cli.app, ["update", "--dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    flat = [" ".join(call) for call in recorder.calls]
    assert any("VIBEDPN_BRANCH=next" in call and call.endswith("install.sh") for call in flat)
    assert any(call.endswith("pull --ignore-pull-failures") for call in flat)
    assert any(" -m vibedpn restart --dir " in call for call in flat)
