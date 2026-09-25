"""The update asked in the panel: the request and result files, the host side, and the API."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from vibedpn import cli
from vibedpn.api.app import create_app
from vibedpn.bootstrap import render_config
from vibedpn.config import Config
from vibedpn.engine.update import (
    UPDATE_TIMEOUT_SECONDS,
    Revision,
    UpdateResult,
    read_revision,
    read_update_request,
    read_update_result,
    render_update_units,
    request_update,
    update_state,
    write_revision,
    write_update_result,
)

from .conftest import home_config

runner = CliRunner()
DATA = Path("data") / "core"


def test_a_request_waits_for_its_result_and_is_not_left_waiting_forever(tmp_path: Path) -> None:
    assert update_state(tmp_path, 100.0).pending is False
    request_update(tmp_path, 100.0)
    assert read_update_request(tmp_path) == 100.0
    assert update_state(tmp_path, 110.0).pending is True
    write_update_result(tmp_path, UpdateResult(100.0, 160.0, True, "updated", "abc1234", "def5678"))
    state = update_state(tmp_path, 170.0)
    assert state.pending is False and state.last == read_update_result(tmp_path)
    request_update(tmp_path, 200.0)  # the host never runs the unit
    silent = update_state(tmp_path, 200.0 + UPDATE_TIMEOUT_SECONDS + 1)
    assert silent.pending is False and silent.last is not None and not silent.last.ok
    assert "journalctl -u vibedpn-update-request" in silent.last.message


def test_the_revision_is_kept_and_a_broken_file_reads_as_none(tmp_path: Path) -> None:
    write_revision(tmp_path, Revision("next", "abc1234", "2026-09-25T10:00:00+03:00"))
    assert read_revision(tmp_path) == Revision("next", "abc1234", "2026-09-25T10:00:00+03:00")
    (tmp_path / "revision.json").write_text("{", encoding="utf-8")
    assert read_revision(tmp_path) is None


def test_the_units_run_one_fixed_command_for_the_request() -> None:
    units = render_update_units(Path("/opt/vibedpn"), "/usr/bin/python3")
    path = units["vibedpn-update-request.path"]
    assert "PathChanged=/opt/vibedpn/data/core/update-request" in path
    service = units["vibedpn-update-request.service"]
    assert "Type=oneshot" in service
    assert "ExecStart=/usr/bin/python3 -m vibedpn update --requested --dir /opt/vibedpn" in service


class Host:
    """A checkout on the host: git answers, install.sh moves the commit, the rest is recorded."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, installs: bool) -> None:
        self.commit = "abc1234"
        self.installs = installs
        self.calls: list[list[str]] = []
        monkeypatch.setattr(cli, "run", self.run)
        monkeypatch.setattr(cli, "capture", self.capture)
        monkeypatch.setattr(cli, "preflight", lambda: None)
        (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
        config = Config.model_validate(home_config())
        (tmp_path / "config.yaml").write_text(render_config(config), encoding="utf-8")
        (tmp_path / "secrets").mkdir()
        (tmp_path / "secrets" / "htpasswd").write_text("admin:x\n", encoding="utf-8")
        (tmp_path / ".git").mkdir()
        (tmp_path / "install.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        (tmp_path / DATA).mkdir(parents=True)

    def run(self, argv: list[str]) -> int:
        self.calls.append(argv)
        if argv[-1].endswith("install.sh"):
            if not self.installs:
                return 1
            self.commit = "def5678"
        return 0

    def capture(self, argv: list[str]) -> str:
        self.calls.append(argv)
        if "rev-parse" in argv:
            return "next\n"
        if "log" in argv:
            return f"{self.commit} 2026-09-25T10:00:00+03:00\n"
        return ""


def test_the_host_runs_the_update_asked_and_writes_what_came_of_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = Host(tmp_path, monkeypatch, installs=True)
    request_update(tmp_path / DATA, 100.0)
    result = runner.invoke(cli.app, ["update", "--requested", "--dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    done = read_update_result(tmp_path / DATA)
    assert done is not None and done.ok and (done.before, done.after) == ("abc1234", "def5678")
    assert "from abc1234 to def5678" in done.message
    assert read_revision(tmp_path / DATA) == Revision(
        "next", "def5678", "2026-09-25T10:00:00+03:00"
    )
    host.calls.clear()
    again = runner.invoke(cli.app, ["update", "--requested", "--dir", str(tmp_path)])
    assert again.exit_code == 0 and host.calls == []  # served already: nothing runs twice


def test_a_failed_update_says_why_and_leaves_the_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    Host(tmp_path, monkeypatch, installs=False)
    request_update(tmp_path / DATA, 100.0)
    result = runner.invoke(cli.app, ["update", "--requested", "--dir", str(tmp_path)])
    assert result.exit_code == 1
    failed = read_update_result(tmp_path / DATA)
    assert failed is not None and not failed.ok
    assert "install.sh failed" in failed.message and failed.before == failed.after == "abc1234"


def test_images_that_never_download_are_the_reason_the_panel_shows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = Host(tmp_path, monkeypatch, installs=True)

    def run(argv: list[str]) -> int:
        if "pull" in argv:
            host.calls.append(argv)
            return 1
        return Host.run(host, argv)

    monkeypatch.setattr(cli, "run", run)
    monkeypatch.setattr(cli, "PULL_PAUSE_SECONDS", 0.0)
    request_update(tmp_path / DATA, 100.0)
    result = runner.invoke(cli.app, ["update", "--requested", "--dir", str(tmp_path)])
    assert result.exit_code == 1
    failed = read_update_result(tmp_path / DATA)
    assert failed is not None and not failed.ok
    assert "did not download after 3 attempts" in failed.message
    assert not any("restart" in argv for argv in host.calls)


def test_the_panel_asks_once_and_sees_the_update_run(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    write_revision(data, Revision("next", "abc1234", "2026-09-25T10:00:00+03:00"))
    client = TestClient(create_app(Config.model_validate(home_config()), data_dir=data))
    shown = client.get("/update").json()
    assert (shown["branch"], shown["commit"], shown["pending"], shown["last"]) == (
        "next",
        "abc1234",
        False,
        None,
    )
    asked = client.post("/update")
    assert asked.status_code == 200 and asked.json()["pending"] is True
    assert read_update_request(data) is not None
    assert client.post("/update").status_code == 409  # one update at a time
    requested = read_update_request(data)
    assert requested is not None
    write_update_result(data, UpdateResult(requested, requested + 60, True, "updated", "a", "b"))
    last = client.get("/update").json()
    assert last["pending"] is False and last["last"]["after"] == "b"
    assert json.loads((data / "update-result.json").read_text(encoding="utf-8"))["ok"] is True
    assert (
        TestClient(create_app(Config.model_validate(home_config()))).get("/update").status_code
        == 404
    )
