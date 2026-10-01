"""vibedpn backup / restore / update with Compose, git and systemctl recorded, not run."""

import json
import shutil
import tarfile
import threading
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vibedpn import cli
from vibedpn.bootstrap import render_config
from vibedpn.config import Config
from vibedpn.engine.apply import (
    BACKUP,
    BOX_DATA_DIR,
    RESTORE,
    read_task_request,
    read_task_result,
    request_task,
)
from vibedpn.engine.backup import RESTORE_SLOT, create_archive

from .conftest import home_config, vps_config
from .test_cli_compose import Recorder
from .test_cli_init import FakeProbe, init_home

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


def init_box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *extra: str) -> Recorder:
    """A box `vibedpn init` made, with every secret `up` checks for; Compose is recorded"""
    monkeypatch.setattr(cli, "HostProbe", FakeProbe)
    code, output = init_home(tmp_path, *extra)
    assert code == 0, output
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    recorder = Recorder()
    monkeypatch.setattr(cli, "run", recorder.run)
    monkeypatch.setattr(cli, "capture", recorder.capture)
    monkeypatch.setattr(cli, "preflight", lambda: None)
    return recorder


def backed_up(tmp_path: Path) -> Path:
    out = tmp_path / "copy.tar.gz"
    result = runner.invoke(cli.app, ["backup", "--out", str(out), "--dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    return out


def test_restore_starts_the_box_from_the_archive_and_keeps_the_old_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = init_box(tmp_path, monkeypatch)
    htpasswd = tmp_path / "secrets" / "htpasswd"
    before = htpasswd.read_text(encoding="utf-8")
    out = backed_up(tmp_path)
    htpasswd.write_text("admin:changed\n", encoding="utf-8")
    recorder.calls.clear()
    result = runner.invoke(cli.app, ["restore", str(out), "--dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert htpasswd.read_text(encoding="utf-8") == before
    assert "previous files are in" in result.output and "restored copy.tar.gz" in result.output
    flat = verbs(recorder)
    assert any(call.endswith("down") for call in flat)
    # the box starts from the archive by itself, and tells core its services
    assert flat[-2].endswith("-d --remove-orphans") and flat[-1].endswith("config --services")


def test_a_restored_box_that_does_not_start_gets_its_files_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = init_box(tmp_path, monkeypatch)
    out = backed_up(tmp_path)
    htpasswd = tmp_path / "secrets" / "htpasswd"
    htpasswd.write_text("admin:changed\n", encoding="utf-8")
    starts: list[int] = []

    def first_up_fails(argv: list[str]) -> int:
        recorder.calls.append(argv)
        if argv[-3:] == ["up", "-d", "--remove-orphans"]:
            starts.append(1)
            return 1 if len(starts) == 1 else 0
        return 0

    monkeypatch.setattr(cli, "run", first_up_fails)
    result = runner.invoke(cli.app, ["restore", str(out), "--dir", str(tmp_path)])
    assert result.exit_code == 1 and "restore undone, the box runs as before" in result.output
    assert htpasswd.read_text(encoding="utf-8") == "admin:changed\n"  # the previous files are back
    assert len(starts) == 2  # and the box started from them
    (failed,) = tmp_path.glob("restore-failed-*")
    assert (failed / "config.yaml").is_file()  # the restored files are kept, not deleted
    assert not list(tmp_path.glob("restore-backup-*"))


def test_an_archive_this_box_cannot_start_is_refused_before_anything_moves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "home").mkdir()
    recorder = init_box(tmp_path / "home", monkeypatch)
    vps = tmp_path / "vps"
    vps.mkdir()
    (vps / "config.yaml").write_text(
        render_config(Config.model_validate(vps_config())), encoding="utf-8"
    )
    foreign = tmp_path / "vps.tar.gz"
    create_archive(vps, foreign)
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "config.yaml").write_text("version: 1\nrole: nobody\n", encoding="utf-8")
    bad = tmp_path / "broken.tar.gz"
    create_archive(broken, bad)
    before = (tmp_path / "home" / "config.yaml").read_text(encoding="utf-8")
    recorder.calls.clear()
    for archive, reason in [(foreign, "the archive is of a vps box"), (bad, "is not a valid box")]:
        result = runner.invoke(cli.app, ["restore", str(archive), "--dir", str(tmp_path / "home")])
        assert result.exit_code == 1 and reason in result.output, result.output
    assert (tmp_path / "home" / "config.yaml").read_text(encoding="utf-8") == before
    assert recorder.calls == [] and not list((tmp_path / "home").glob("restore-*"))


def test_a_backup_beyond_keep_removes_the_oldest_archives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    init_box(tmp_path, monkeypatch)
    config = tmp_path / "config.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("  keep: 10\n", "  keep: 2\n"), encoding="utf-8"
    )
    backups = tmp_path / "backups"
    backups.mkdir()
    for old in ("vibedpn-20260101-000000.tar.gz", "vibedpn-20260102-000000.tar.gz"):
        (backups / old).write_bytes(b"old")
    (backups / "notes.txt").write_text("not an archive of the box\n", encoding="utf-8")
    result = runner.invoke(cli.app, ["backup", "--dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "removed the old vibedpn-20260101-000000.tar.gz (backup.keep)" in result.output
    assert result.output.splitlines()[-1].startswith("wrote ")  # scripts/pullBackup.sh reads it
    names = sorted(entry.name for entry in backups.iterdir())
    assert len(names) == 3 and "vibedpn-20260102-000000.tar.gz" in names and "notes.txt" in names


def test_the_panel_asks_and_the_host_backs_up_and_restores_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    init_box(tmp_path, monkeypatch)
    data = tmp_path / BOX_DATA_DIR
    data.mkdir(parents=True, exist_ok=True)
    request_task(data, BACKUP, 100.0, "backup asked in the panel")
    result = runner.invoke(cli.app, ["backup", "--requested", "--dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    made = read_task_result(data, BACKUP)
    assert made is not None and made.ok and made.requested_at == 100.0
    assert (tmp_path / "backups" / made.message).is_file()  # the result names the archive
    again = runner.invoke(cli.app, ["backup", "--requested", "--dir", str(tmp_path)])
    assert again.exit_code == 0 and len(list((tmp_path / "backups").iterdir())) == 1  # once
    # the archive does not carry the request: restoring it must not ask for a backup again
    with tarfile.open(tmp_path / "backups" / made.message) as tar:
        assert "data/core/backup-request" not in tar.getnames()

    htpasswd = tmp_path / "secrets" / "htpasswd"
    before = htpasswd.read_text(encoding="utf-8")
    htpasswd.write_text("admin:changed\n", encoding="utf-8")
    slot = tmp_path / "backups" / RESTORE_SLOT
    shutil.copy(tmp_path / "backups" / made.message, slot)
    request_task(data, RESTORE, 200.0, "restore asked in the panel")
    result = runner.invoke(cli.app, ["restore", "--requested", "--dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert htpasswd.read_text(encoding="utf-8") == before and not slot.exists()
    restored = read_task_result(data, RESTORE)  # in the data/core the archive brought
    assert restored is not None and restored.ok and restored.requested_at == 200.0
    assert read_task_request(data, BACKUP) is None  # nothing replays
    both = runner.invoke(cli.app, ["restore", str(slot), "--requested", "--dir", str(tmp_path)])
    assert both.exit_code != 0


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


def test_a_task_the_unit_and_the_owner_both_run_is_done_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The path unit and a hand-run command both see the request: the second waits for the lock,
    then finds the result written"""
    init_box(tmp_path, monkeypatch)
    data = tmp_path / BOX_DATA_DIR
    data.mkdir(parents=True, exist_ok=True)
    request_task(data, BACKUP, 100.0, "backup asked in the panel")
    runs: list[str] = []
    started = threading.Event()

    def slow() -> str:
        runs.append("work")
        started.set()
        time.sleep(0.3)
        return "vibedpn-20261001-120000.tar.gz"

    first = threading.Thread(target=cli._run_requested, args=(tmp_path, BACKUP, slow))
    first.start()
    assert started.wait(5)
    cli._run_requested(tmp_path, BACKUP, slow)  # blocks until the first one is done
    first.join()
    assert runs == ["work"]
    made = read_task_result(data, BACKUP)
    assert made is not None and made.ok
