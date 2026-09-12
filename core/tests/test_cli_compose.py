"""up / down / restart / status / logs with Compose replaced by a recorder."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from vibedpn import cli
from vibedpn.api.client import CoreUnreachableError, StatsUnavailableError
from vibedpn.bootstrap import Answers, HostFacts, build_config, render_config
from vibedpn.config import Config, Role
from vibedpn.engine.myst import ProviderStats, SessionTotals

from .conftest import client_config

runner = CliRunner()


class Recorder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.exit_code = 0
        self.ps_output = ""
        self.all_services = "core\nmyst-provider\nwg-server\n"
        self.active_services = "core\nmyst-provider\nwg-server\n"

    def run(self, argv: list[str]) -> int:
        self.calls.append(argv)
        return self.exit_code

    def capture(self, argv: list[str]) -> str:
        self.calls.append(argv)
        if argv[-2:] == ["config", "--services"]:
            return self.all_services if "--profile" in argv else self.active_services
        return self.ps_output


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Recorder]:
    recorder = Recorder()
    monkeypatch.setattr(cli, "run", recorder.run)
    monkeypatch.setattr(cli, "capture", recorder.capture)
    monkeypatch.setattr(cli, "preflight", lambda: None)
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    config = build_config(Answers(Role.VPS, endpoint="vps.example.com"), HostFacts(None, True))
    (tmp_path / "config.yaml").write_text(render_config(config), encoding="utf-8")
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "htpasswd").write_text("admin:x\n", encoding="utf-8")
    (tmp_path / "data" / "myst-provider").mkdir(parents=True)
    (tmp_path / "data" / "myst-provider" / "nodeui-pass").write_text("$2b$x\n", encoding="utf-8")
    return tmp_path, recorder


def tail(argv: list[str]) -> list[str]:
    return argv[4:]  # after: docker compose --project-directory <dir>


def test_up_refreshes_env_and_starts(box: tuple[Path, Recorder]) -> None:
    box_dir, recorder = box
    result = runner.invoke(cli.app, ["up", "--dir", str(box_dir)])
    assert result.exit_code == 0, result.output
    assert [tail(c) for c in recorder.calls] == [
        ["--profile", "*", "config", "--services"],
        ["config", "--services"],
        ["up", "-d", "--remove-orphans"],
    ]
    assert "COMPOSE_PROFILES=provider,wg-server" in (box_dir / ".env").read_text(encoding="utf-8")


def test_up_retires_containers_of_dropped_profiles(box: tuple[Path, Recorder]) -> None:
    box_dir, recorder = box
    recorder.all_services = "core\nmyst-provider\nmyst-consumer\nwg-server\nadguard\n"
    recorder.active_services = "core\nmyst-provider\nwg-server\n"
    result = runner.invoke(cli.app, ["up", "--dir", str(box_dir)])
    assert result.exit_code == 0, result.output
    assert tail(recorder.calls[2]) == [
        "--profile",
        "*",
        "rm",
        "--stop",
        "--force",
        "adguard",
        "myst-consumer",
    ]
    assert tail(recorder.calls[3]) == ["up", "-d", "--remove-orphans"]


def test_up_refuses_without_the_node_password(box: tuple[Path, Recorder]) -> None:
    box_dir, recorder = box
    (box_dir / "data" / "myst-provider" / "nodeui-pass").unlink()
    result = runner.invoke(cli.app, ["up", "--dir", str(box_dir)])
    assert result.exit_code == 1
    assert "missing nodeui-pass" in result.output and "init --force" in result.output
    assert recorder.calls == []


def test_down_covers_every_profile(box: tuple[Path, Recorder]) -> None:
    box_dir, recorder = box
    assert runner.invoke(cli.app, ["down", "--dir", str(box_dir)]).exit_code == 0
    assert tail(recorder.calls[0]) == ["--profile", "*", "down"]
    assert not (box_dir / ".env").exists()  # down does not derive .env


def test_restart_recreates_then_restarts(box: tuple[Path, Recorder]) -> None:
    box_dir, recorder = box
    assert runner.invoke(cli.app, ["restart", "--dir", str(box_dir)]).exit_code == 0
    assert [tail(c) for c in recorder.calls][2:] == [["up", "-d", "--remove-orphans"], ["restart"]]


def test_logs_passes_service_follow_and_tail(box: tuple[Path, Recorder]) -> None:
    box_dir, recorder = box
    result = runner.invoke(cli.app, ["logs", "core", "-f", "--tail", "20", "--dir", str(box_dir)])
    assert result.exit_code == 0, result.output
    assert tail(recorder.calls[0]) == ["--profile", "*", "logs", "--tail", "20", "--follow", "core"]


def test_status_prints_config_and_containers(box: tuple[Path, Recorder]) -> None:
    box_dir, recorder = box
    recorder.ps_output = (
        '{"Service":"core","State":"running","Health":"healthy","Status":"Up 9s (healthy)"}\n'
    )
    result = runner.invoke(cli.app, ["status", "--dir", str(box_dir)])
    assert result.exit_code == 0, result.output
    assert "role: vps" in result.output
    assert "profiles: provider,wg-server" in result.output
    assert "core  running  healthy   Up 9s (healthy)" in result.output
    assert tail(recorder.calls[0]) == ["ps", "-a", "--format", "json"]


def test_status_without_containers(box: tuple[Path, Recorder]) -> None:
    box_dir, _ = box
    result = runner.invoke(cli.app, ["status", "--dir", str(box_dir)])
    assert "containers: none (run `vibedpn up`)" in result.output
    assert "node:" not in result.output


CORE_UP = '{"Service":"core","State":"running","Health":"healthy","Status":"Up 9s (healthy)"}\n'


def test_status_prints_the_node_block_from_core(
    box: tuple[Path, Recorder], monkeypatch: pytest.MonkeyPatch
) -> None:
    box_dir, recorder = box
    recorder.ps_output = CORE_UP
    ports: list[int] = []

    def fake_fetch(port: int) -> ProviderStats:
        ports.append(port)
        return ProviderStats(
            node_version="1.39.5",
            node_uptime="1m",
            monitoring_status="unknown",
            identity=None,
            services=[],
            sessions=SessionTotals(),
        )

    monkeypatch.setattr(cli, "fetch_provider_stats", fake_fetch)
    result = runner.invoke(cli.app, ["status", "--dir", str(box_dir)])
    assert result.exit_code == 0, result.output
    assert ports == [4480]
    assert "node: myst 1.39.5, up 1m, monitoring unknown" in result.output
    assert "identity: none yet" in result.output


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (CoreUnreachableError("ConnectError: refused"), "node: core is not running"),
        (StatsUnavailableError("TequilAPI /healthcheck: HTTP 500"), "node: unavailable (TequilAPI"),
    ],
)
def test_status_explains_a_missing_node_block(
    box: tuple[Path, Recorder], monkeypatch: pytest.MonkeyPatch, error: Exception, expected: str
) -> None:
    box_dir, recorder = box
    recorder.ps_output = CORE_UP

    def fail(port: int) -> ProviderStats:
        raise error

    monkeypatch.setattr(cli, "fetch_provider_stats", fail)
    result = runner.invoke(cli.app, ["status", "--dir", str(box_dir)])
    assert result.exit_code == 0, result.output
    assert expected in result.output


def test_status_skips_the_node_block_without_a_provider(
    box: tuple[Path, Recorder], monkeypatch: pytest.MonkeyPatch
) -> None:
    box_dir, recorder = box
    recorder.ps_output = CORE_UP
    config = Config.model_validate(client_config())
    (box_dir / "config.yaml").write_text(render_config(config), encoding="utf-8")

    def fail(port: int) -> ProviderStats:
        raise AssertionError("core must not be asked")

    monkeypatch.setattr(cli, "fetch_provider_stats", fail)
    result = runner.invoke(cli.app, ["status", "--dir", str(box_dir)])
    assert result.exit_code == 0, result.output
    assert "node:" not in result.output


def test_compose_exit_code_is_propagated(box: tuple[Path, Recorder]) -> None:
    box_dir, recorder = box
    recorder.exit_code = 17
    assert runner.invoke(cli.app, ["up", "--dir", str(box_dir)]).exit_code == 17


def test_commands_need_an_initialised_box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "preflight", lambda: None)
    result = runner.invoke(cli.app, ["up", "--dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "install.sh" in result.output
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    result = runner.invoke(cli.app, ["status", "--dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "vibedpn init" in result.output
