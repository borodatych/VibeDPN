"""The check of the box from the panel: core asks the host, the host keeps the report core shows
(api/doctor.py, `vibedpn doctor --requested` and `--report`)"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from vibedpn import cli
from vibedpn.api.app import create_app
from vibedpn.api.doctor import read_report
from vibedpn.api.models import DoctorReportView
from vibedpn.config import Config
from vibedpn.doctor import REPORT_FILE, CheckResult, Verdict
from vibedpn.engine.apply import (
    BOX_DATA_DIR,
    DOCTOR,
    read_task_reason,
    read_task_result,
    request_task,
)

from .conftest import home_config

runner = CliRunner()
CHECKS = [
    CheckResult("router", Verdict.OK, "routing.mode full"),
    CheckResult("exit dpn", Verdict.WARN, "no session", "register the consumer identity"),
]


def app(tmp_path: Path) -> tuple[TestClient, Path]:
    data = tmp_path / "data"
    data.mkdir()
    return TestClient(create_app(Config.model_validate(home_config()), data_dir=data)), data


def test_a_check_is_asked_of_the_host_with_its_word(tmp_path: Path) -> None:
    client, data = app(tmp_path)
    shown = client.get("/doctor").json()
    assert shown["report"] is None and shown["state"]["pending"] is False
    asked = client.post("/doctor", json={"network": True})
    assert asked.status_code == 200 and asked.json()["state"]["pending"] is True
    assert read_task_reason(data, DOCTOR) == "network"
    assert client.post("/doctor", json={}).status_code == 409  # one check at a time


def test_the_kept_report_is_shown_and_a_broken_one_is_none(tmp_path: Path) -> None:
    client, data = app(tmp_path)
    report = {
        "finished_at": 1790000000.0,
        "network": False,
        "checks": [{"name": "router", "verdict": "ok", "detail": "routing.mode full", "hint": ""}],
    }
    (data / REPORT_FILE).write_text(json.dumps(report), encoding="utf-8")
    assert client.get("/doctor").json()["report"] == report
    (data / REPORT_FILE).write_text("{", encoding="utf-8")
    assert client.get("/doctor").json()["report"] is None


def test_a_check_the_host_never_ran_blocks_nothing(tmp_path: Path) -> None:
    client, data = app(tmp_path)
    request_task(data, DOCTOR, time.time() - DOCTOR.timeout - 1, "local")
    state = client.get("/doctor").json()["state"]
    assert state["pending"] is False and state["ok"] is False
    assert client.post("/doctor", json={}).status_code == 200


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """The checks themselves are the host's: recorded here, with the network flag they got"""
    (tmp_path / BOX_DATA_DIR).mkdir(parents=True)
    asked: list[bool] = []

    def gather(_box_dir: Path, *, network: bool = False) -> object:
        asked.append(network)
        return object()

    monkeypatch.setattr(cli, "gather", gather)
    monkeypatch.setattr(cli, "evaluate", lambda _facts: CHECKS)
    return asked


def report_of(tmp_path: Path) -> DoctorReportView:
    """The report as core reads it: what the host writes, core must understand"""
    report = read_report(tmp_path / BOX_DATA_DIR)
    assert report is not None
    return report


def test_the_host_checks_once_and_leaves_the_box_only_for_the_word_network(
    tmp_path: Path, host: list[bool]
) -> None:
    data = tmp_path / BOX_DATA_DIR
    request_task(data, DOCTOR, 100.0, "network")
    result = runner.invoke(cli.app, ["doctor", "--requested", "--dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    done = read_task_result(data, DOCTOR)
    assert done is not None and done.ok and done.message == "1 ok, 1 warn, 0 fail"
    report = report_of(tmp_path)
    assert report.network is True and [check.verdict for check in report.checks] == ["ok", "warn"]
    assert report.checks[1].hint == "register the consumer identity"
    runner.invoke(cli.app, ["doctor", "--requested", "--dir", str(tmp_path)])
    assert host == [True]  # done once
    request_task(data, DOCTOR, 200.0, "network; rm -rf /")  # only the exact word counts
    runner.invoke(cli.app, ["doctor", "--requested", "--dir", str(tmp_path)])
    assert host == [True, False] and report_of(tmp_path).network is False


def test_the_daily_check_keeps_a_report_without_a_request(tmp_path: Path, host: list[bool]) -> None:
    result = runner.invoke(cli.app, ["doctor", "--report", "--dir", str(tmp_path)])
    assert result.exit_code == 0 and "1 ok, 1 warn, 0 fail" in result.output
    assert host == [False] and report_of(tmp_path).network is False
    both = runner.invoke(cli.app, ["doctor", "--report", "--requested", "--dir", str(tmp_path)])
    assert both.exit_code == 1
