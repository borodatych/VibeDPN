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
    assert any(call.endswith(" pull") for call in flat)
    assert not any(
        "--ignore-pull-failures" in call for call in flat
    )  # a failed pull is not forgiven
    assert any(" -m vibedpn restart --dir " in call for call in flat)


def test_update_refreshes_the_images_of_disabled_services_the_host_keeps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = make_box(tmp_path, monkeypatch)
    (tmp_path / ".git").mkdir()
    (tmp_path / "install.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    recorder.ps_output = "next\n"
    recorder.all_services = "core\naccess\nwg-server\nxray\n"
    recorder.active_services = "core\n"
    recorder.config_json = json.dumps(
        {
            "services": {
                "core": {"image": "ghcr.io/o/vibedpn-core:next"},
                "access": {"image": "ghcr.io/o/vibedpn-xray:next"},
                "wg-server": {"image": "ghcr.io/o/vibedpn-wg:next"},
                "xray": {"image": "ghcr.io/o/vibedpn-xray:next"},
            }
        }
    )
    # an uplink tried once left its image behind; wg was never pulled here
    recorder.image_listing = "ghcr.io/o/vibedpn-core:next\nghcr.io/o/vibedpn-xray:next\n"
    result = runner.invoke(cli.app, ["update", "--dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    pulls = [call for call in recorder.calls if "pull" in call]
    assert [call[call.index("pull") :] for call in pulls] == [
        ["pull"],
        ["pull", "access", "xray"],
    ]
    assert "--profile" in pulls[1]  # disabled services are named only under every profile
    flat = [" ".join(call) for call in recorder.calls]
    pulled = flat.index(" ".join(pulls[1]))
    restarted = next(i for i, call in enumerate(flat) if " -m vibedpn restart " in call)
    assert pulled < restarted


class FlakyPulls:
    """Compose whose pulls fail ``failures`` times first; ``broken`` services never pull alone."""

    def __init__(self, recorder: Recorder, failures: int, broken: tuple[str, ...] = ()) -> None:
        self.recorder = recorder
        self.failures = failures
        self.broken = broken

    def run(self, argv: list[str]) -> int:
        self.recorder.calls.append(argv)
        if "pull" not in argv:
            return 0
        named = argv[argv.index("pull") + 1 :]
        if named and not set(named) & set(self.broken):
            return 0
        if self.failures:
            self.failures -= 1
            return 1
        return 1 if set(named) & set(self.broken) else 0


def update_box(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failures: int, broken: tuple[str, ...] = ()
) -> tuple[Recorder, str, int]:
    recorder = make_box(tmp_path, monkeypatch)
    (tmp_path / ".git").mkdir()
    (tmp_path / "install.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    recorder.ps_output = "next\n"
    recorder.active_services = recorder.all_services = "core\nhostapd\ntor\n"
    monkeypatch.setattr(cli, "run", FlakyPulls(recorder, failures, broken).run)
    monkeypatch.setattr(cli, "PULL_PAUSE_SECONDS", 0.0)
    result = runner.invoke(cli.app, ["update", "--dir", str(tmp_path)])
    return recorder, result.output, result.exit_code


def test_a_pull_that_timed_out_is_tried_again_and_the_update_goes_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One address of ghcr.io is a black hole on some lines: the next try usually gets another."""
    recorder, output, code = update_box(tmp_path, monkeypatch, failures=1)
    assert code == 0, output
    assert "pulling the images failed (attempt 1 of 3); trying again" in output
    flat = [" ".join(call) for call in recorder.calls]
    assert sum(call.endswith(" pull") for call in flat) == 2
    assert any(" -m vibedpn restart " in call for call in flat)


def test_images_that_never_download_stop_the_update_before_the_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Saying "updated" over a core that was not replaced is what a forgiven pull did."""
    recorder, output, code = update_box(
        tmp_path, monkeypatch, failures=3, broken=("core", "hostapd")
    )
    assert code == 1
    assert "the images of core, hostapd did not download after 3 attempts" in output
    assert "keeps running the previous version" in output
    flat = [" ".join(call) for call in recorder.calls]
    assert sum(call.endswith(" pull") for call in flat) == 3
    assert not any(" -m vibedpn restart " in call for call in flat)
