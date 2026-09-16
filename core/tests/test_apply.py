"""WireGuard exits added in the panel and applied by the host: API, request and systemd units."""

import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import typer
from fastapi.testclient import TestClient

from vibedpn import cli
from vibedpn.api.app import create_app
from vibedpn.api.state import BoxState
from vibedpn.bootstrap import render_config
from vibedpn.config import Config, load_config
from vibedpn.engine.apply import (
    APPLY_TIMEOUT_SECONDS,
    BOX_DATA_DIR,
    ApplyResult,
    apply_state,
    read_request,
    read_result,
    render_units,
    request_apply,
    write_result,
)

from .conftest import home_config, vps_config

PROVIDER_FILE = (
    "[Interface]\nPrivateKey = aGVsbG8taS1hbS1hLXRlc3Qta2V5LW5vdC1hLXJlYWw=\n"
    "Address = 10.2.0.2/32\n"
    "DNS = 10.2.0.1\n\n[Peer]\nPublicKey = cGVlci1wdWJsaWMta2V5LWZvci10ZXN0cy1vbmx5LTA=\n"
    "AllowedIPs = 0.0.0.0/0\nEndpoint = 203.0.113.10:51820\n"
)


def box(tmp_path: Path, raw: dict[str, Any] | None = None) -> tuple[TestClient, Path]:
    config = Config.model_validate(raw or home_config())
    path = tmp_path / "config.yaml"
    path.write_text(render_config(config), encoding="utf-8")
    (tmp_path / "secrets").mkdir(mode=0o700)
    (tmp_path / "data").mkdir()
    state = BoxState(config, path, apply=lambda _config: [])
    app = create_app(
        config, state=state, secrets_dir=tmp_path / "secrets", data_dir=tmp_path / "data"
    )
    return TestClient(app), path


# --- the request and the result ----------------------------------------------------------------


def test_a_request_is_pending_until_a_result_covers_it(tmp_path: Path) -> None:
    assert apply_state(tmp_path, 0.0).pending is False and read_request(tmp_path) is None
    request_apply(tmp_path, 100.0, "exit added")
    assert read_request(tmp_path) == 100.0
    assert apply_state(tmp_path, 110.0).pending is True
    write_result(tmp_path, ApplyResult(100.0, 130.0, True, "applied"))
    state = apply_state(tmp_path, 140.0)
    assert state.pending is False and state.last == ApplyResult(100.0, 130.0, True, "applied")
    request_apply(tmp_path, 200.0, "exit removed")  # a later change waits again
    assert apply_state(tmp_path, 210.0).pending is True


def test_a_request_the_host_never_answers_is_reported_not_left_applying(tmp_path: Path) -> None:
    """Found on the box: the unit failed before writing a result, and the panel said "applying"
    for good. After the timeout the panel says the host did not apply it, and where to look."""
    request_apply(tmp_path, 100.0, "exit added")
    assert apply_state(tmp_path, 100.0 + APPLY_TIMEOUT_SECONDS - 1).pending is True
    state = apply_state(tmp_path, 100.0 + APPLY_TIMEOUT_SECONDS + 1)
    assert state.pending is False
    assert state.last is not None and not state.last.ok
    assert "journalctl -u vibedpn-apply" in state.last.message


def test_the_cli_runs_as_python_m_vibedpn() -> None:
    """The units and `vibedpn update` start the CLI as `python -m vibedpn`: found on the box that
    the package had no __main__ and every such start failed."""
    result = subprocess.run(
        [sys.executable, "-m", "vibedpn", "--version"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("vibedpn ")


def test_the_units_watch_the_request_and_run_apply_for_the_box(tmp_path: Path) -> None:
    units = render_units(Path("/opt/vibedpn"), "/opt/vibedpn/venv/bin/python")
    assert "PathChanged=/opt/vibedpn/data/core/apply-request\n" in units["vibedpn-apply.path"]
    service = units["vibedpn-apply.service"]
    assert "Type=oneshot\n" in service
    assert "ExecStart=/opt/vibedpn/venv/bin/python -m vibedpn apply --dir /opt/vibedpn\n" in service


# --- the API -------------------------------------------------------------------------------------


def test_an_exit_from_the_panel_is_saved_private_and_asked_to_be_applied(tmp_path: Path) -> None:
    client, path = box(tmp_path)
    answer = client.post("/uplinks/wg", json={"name": "proton", "config": PROVIDER_FILE})
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["uplinks"] == [{"name": "proton", "enabled": True, "has_file": True}]
    assert body["apply"]["pending"] is True
    # the key is on the box, readable by root only, and never comes back through the API
    saved = tmp_path / "secrets" / "wg-proton.conf"
    assert saved.read_text(encoding="utf-8") == PROVIDER_FILE
    assert stat.S_IMODE(saved.stat().st_mode) == 0o600
    assert "PrivateKey" not in answer.text
    assert load_config(path).upstreams.wg["proton"].enabled
    assert read_request(tmp_path / "data") is not None


def test_a_file_that_is_not_a_provider_file_or_a_bad_name_changes_nothing(tmp_path: Path) -> None:
    client, path = box(tmp_path)
    before = path.read_text(encoding="utf-8")
    notes = client.post("/uplinks/wg", json={"name": "proton", "config": "hello\n"})
    assert notes.status_code == 422
    assert "[Interface]" in notes.json()["detail"]
    bad = client.post("/uplinks/wg", json={"name": "../etc", "config": PROVIDER_FILE})
    assert bad.status_code == 422
    assert path.read_text(encoding="utf-8") == before
    assert list((tmp_path / "secrets").iterdir()) == []
    assert read_request(tmp_path / "data") is None


def test_removing_an_exit_takes_its_key_away(tmp_path: Path) -> None:
    client, path = box(tmp_path)
    client.post("/uplinks/wg", json={"name": "proton", "config": PROVIDER_FILE})
    answer = client.delete("/uplinks/wg/proton")
    assert answer.status_code == 200, answer.text
    assert answer.json()["uplinks"] == []
    assert not (tmp_path / "secrets" / "wg-proton.conf").exists()
    assert "proton" not in load_config(path).upstreams.wg
    assert client.delete("/uplinks/wg/proton").status_code == 404


def test_the_exit_the_lan_goes_through_is_not_removed(tmp_path: Path) -> None:
    raw = home_config()
    raw["upstreams"]["wg"] = {"proton": {}}
    raw["routing"] = {"mode": "full", "default_upstream": "wg-proton"}
    client, _path = box(tmp_path, raw)
    (tmp_path / "secrets" / "wg-proton.conf").write_text(PROVIDER_FILE, encoding="utf-8")
    answer = client.delete("/uplinks/wg/proton")
    assert answer.status_code == 422
    assert (tmp_path / "secrets" / "wg-proton.conf").exists()


def test_a_box_without_a_lan_takes_no_exits_from_the_panel(tmp_path: Path) -> None:
    client = TestClient(create_app(Config.model_validate(vps_config())))
    assert client.get("/uplinks/wg").status_code == 404


# --- vibedpn apply -------------------------------------------------------------------------------


def test_apply_runs_up_once_per_request_and_catches_a_change_made_meanwhile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / BOX_DATA_DIR
    data.mkdir(parents=True)
    runs: list[int] = []

    def fake_up(box_dir: Path) -> None:
        runs.append(1)
        if len(runs) == 1:  # the owner adds another exit while the first `up` runs
            request_apply(data, 200.0, "another exit")

    monkeypatch.setattr(cli, "up", fake_up)
    request_apply(data, 100.0, "exit added")
    cli.apply(tmp_path)
    assert len(runs) == 2
    last = read_result(data)
    assert last is not None and last.requested_at == 200.0 and last.ok
    cli.apply(tmp_path)  # nothing new: nothing runs
    assert len(runs) == 2


def test_a_failed_up_is_reported_to_the_panel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / BOX_DATA_DIR
    data.mkdir(parents=True)

    def failing_up(box_dir: Path) -> None:
        raise typer.Exit(1)

    monkeypatch.setattr(cli, "up", failing_up)
    request_apply(data, 100.0, "exit added")
    with pytest.raises(typer.Exit):
        cli.apply(tmp_path)
    last = read_result(data)
    assert last is not None and not last.ok
    assert "journalctl -u vibedpn-apply" in last.message


def test_up_installs_the_units_once_and_enables_the_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(cli, "SYSTEMD_DIR", tmp_path)
    monkeypatch.setattr(cli, "find_tool", lambda name: "/usr/bin/systemctl")
    monkeypatch.setattr("os.geteuid", lambda: 0)

    def fake_run(argv: list[str]) -> int:
        commands.append(argv[1:])
        return 0

    monkeypatch.setattr(cli, "run", fake_run)
    cli._ensure_apply_units(Path("/opt/vibedpn"))
    assert (tmp_path / "vibedpn-apply.path").is_file()
    assert commands == [["daemon-reload"], ["enable", "--now", "vibedpn-apply.path"]]
    commands.clear()
    cli._ensure_apply_units(Path("/opt/vibedpn"))  # already current and enabled
    assert commands == [["is-enabled", "--quiet", "vibedpn-apply.path"]]


def test_tor_is_turned_on_from_the_panel_and_the_host_asked_to_start_it(tmp_path: Path) -> None:
    client, path = box(tmp_path)
    shown = client.get("/uplinks/tor")
    assert shown.status_code == 200, shown.text
    assert shown.json()["enabled"] is False
    assert shown.json()["bridges"] == ["snowflake 192.0.2.3:80", "snowflake 192.0.2.4:80"]
    assert read_request(tmp_path / "data") is None
    answer = client.put("/uplinks/tor", json={"enabled": True})
    assert answer.status_code == 200, answer.text
    assert answer.json()["enabled"] is True and answer.json()["apply"]["pending"] is True
    assert load_config(path).upstreams.tor.enabled
    first = read_request(tmp_path / "data")
    assert first is not None
    # the same state again changes nothing and asks the host for nothing new
    assert client.put("/uplinks/tor", json={"enabled": True}).status_code == 200
    assert read_request(tmp_path / "data") == first


def test_tor_the_lan_goes_through_is_not_turned_off(tmp_path: Path) -> None:
    raw = home_config()
    raw["upstreams"]["tor"] = {"enabled": True}
    raw["routing"] = {"mode": "full", "default_upstream": "tor"}
    client, path = box(tmp_path, raw)
    answer = client.put("/uplinks/tor", json={"enabled": False})
    assert answer.status_code == 422
    assert "not an enabled uplink" in answer.json()["detail"]
    assert load_config(path).upstreams.tor.enabled
