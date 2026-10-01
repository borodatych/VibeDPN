"""Container logs from the panel: core asks the host, the host reads only a service of this box
and cleans the lines of secrets (engine/logs.py, api/logs.py, `vibedpn logs --requested`)"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from vibedpn import cli
from vibedpn.api.app import create_app
from vibedpn.api.logs import read_report
from vibedpn.config import Config
from vibedpn.engine.apply import (
    BOX_DATA_DIR,
    LOGS,
    read_task_reason,
    read_task_result,
    request_task,
)
from vibedpn.engine.logs import (
    MAX_TAIL,
    REPORT_FILE,
    SERVICES_FILE,
    LogsError,
    LogsRequest,
    parse_request,
    redact,
)

from .conftest import home_config

runner = CliRunner()
SERVICES = ["core", "tor", "wg-client", "xray"]
WG_KEY = "yAnz5TF+lXXJte14tji3zlMNq+hd2rYUIgJBgB3fBmk="
REALITY_KEY = "SbVKOEMjK0sIlbwg4akyBg5mL5KZwwB-ed4eEE7YnRc"


@pytest.mark.parametrize(
    ("line", "cleaned"),
    [
        (
            "accepted vless://0b9c3f7e-1d2a-4c5b-8e6f-7a8b9c0d1e2f@5.139.228.15:443?sni=x",
            "accepted vless://***@5.139.228.15:443?sni=x",
        ),
        (
            "POST https://api.telegram.org/bot123456789:AAH4kZ9xQ-abcdefghijklmnopqrstuvwxy/send",
            "POST https://api.telegram.org/bot***/send",
        ),
        (
            "GET https://www.duckdns.org/update?domains=box&token=abc123",
            "GET https://www.duckdns.org/update?domains=box&token=***",
        ),
        ("proxy socks5://user:hunter2@10.0.0.1:1080", "proxy socks5://***@10.0.0.1:1080"),
        ("user 0b9c3f7e-1d2a-4c5b-8e6f-7a8b9c0d1e2f added", "user *** added"),
        (f"peer {WG_KEY} handshake", "peer *** handshake"),
        (f"privateKey: {REALITY_KEY}", "privateKey: ***"),
        ("wpa_passphrase=secret words here", "wpa_passphrase=*** words here"),
    ],
)
def test_secrets_never_leave_the_host(line: str, cleaned: str) -> None:
    assert redact(line) == cleaned


def test_ordinary_lines_are_left_as_they_are() -> None:
    line = "2026-10-01 10:00:00 [notice] Bootstrapped 100% (done): container 3f9da31c0ffee0123 up"
    assert redact(line) == line


def test_the_host_reads_only_a_service_of_this_box() -> None:
    assert parse_request("tor 50", SERVICES) == LogsRequest("tor", 50)
    for word in ("tor", "tor 0", f"tor {MAX_TAIL + 1}", "myst-provider 10", "tor; rm 10", "../x 1"):
        with pytest.raises(LogsError):
            parse_request(word, SERVICES)


def app(tmp_path: Path) -> tuple[TestClient, Path]:
    data = tmp_path / "data"
    data.mkdir()
    (data / SERVICES_FILE).write_text("".join(f"{s}\n" for s in SERVICES), encoding="utf-8")
    return TestClient(create_app(Config.model_validate(home_config()), data_dir=data)), data


def test_a_log_is_asked_of_the_host_for_a_service_up_named(tmp_path: Path) -> None:
    client, data = app(tmp_path)
    shown = client.get("/logs").json()
    assert shown["services"] == SERVICES and shown["report"] is None
    assert client.post("/logs", json={"service": "adguard"}).status_code == 422
    assert client.post("/logs", json={"service": "tor", "tail": MAX_TAIL + 1}).status_code == 422
    asked = client.post("/logs", json={"service": "tor", "tail": 30})
    assert asked.status_code == 200 and asked.json()["state"]["pending"] is True
    assert read_task_reason(data, LOGS) == "tor 30"
    assert client.post("/logs", json={"service": "xray"}).status_code == 409  # one at a time


def test_before_the_first_up_nothing_is_offered(tmp_path: Path) -> None:
    client, data = app(tmp_path)
    (data / SERVICES_FILE).unlink()
    assert client.get("/logs").json()["services"] == []
    assert client.post("/logs", json={"service": "core"}).status_code == 422


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Docker is the host's: the services of the box and the lines of a log, recorded here"""
    (tmp_path / BOX_DATA_DIR).mkdir(parents=True)
    (tmp_path / "config.yaml").write_text("role: home\n", encoding="utf-8")
    asked: list[list[str]] = []

    def stream(argv: list[str]) -> Iterator[str]:
        asked.append(argv)
        yield "Bootstrapped 100%"
        yield "bridge obfs4 token=s3cret"

    monkeypatch.setattr(cli, "_prepare", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli, "capture", lambda _argv: "\n".join(SERVICES) + "\n")
    monkeypatch.setattr(cli, "stream", stream)
    return asked


def test_the_host_reads_the_log_once_and_keeps_it_cleaned(
    tmp_path: Path, host: list[list[str]]
) -> None:
    data = tmp_path / BOX_DATA_DIR
    request_task(data, LOGS, time.time(), "tor 20")
    result = runner.invoke(cli.app, ["logs", "--requested", "--dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    done = read_task_result(data, LOGS)
    assert done is not None and done.ok and done.message == "2 lines of tor"
    assert host[0][-6:] == ["logs", "--no-color", "--no-log-prefix", "--tail", "20", "tor"]
    report = read_report(data)  # what the host writes, core must understand
    assert report is not None and report.service == "tor" and report.tail == 20
    assert report.text == "Bootstrapped 100%\nbridge obfs4 token=***"
    runner.invoke(cli.app, ["logs", "--requested", "--dir", str(tmp_path)])
    assert len(host) == 1  # done once


def test_a_service_the_box_does_not_run_is_refused_without_docker(
    tmp_path: Path, host: list[list[str]]
) -> None:
    data = tmp_path / BOX_DATA_DIR
    request_task(data, LOGS, time.time(), "adguard 20")
    result = runner.invoke(cli.app, ["logs", "--requested", "--dir", str(tmp_path)])
    assert result.exit_code == 1
    done = read_task_result(data, LOGS)
    assert done is not None and not done.ok and host == []
    assert not (data / REPORT_FILE).exists()
