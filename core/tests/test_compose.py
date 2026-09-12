"""Compose layer: argv, preconditions, ps parsing, preflight error mapping."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from vibedpn import compose
from vibedpn.bootstrap import Answers, HostFacts, build_config, render_config
from vibedpn.compose import (
    ComposeError,
    ServiceStatus,
    check_box,
    compose_argv,
    parse_ps,
    preflight,
    refresh_env,
)
from vibedpn.config import Role


def make_box(tmp_path: Path) -> Path:
    box = tmp_path / "box"
    box.mkdir()
    (box / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    config = build_config(Answers(Role.VPS, endpoint="vps.example.com"), HostFacts(None, True))
    (box / "config.yaml").write_text(render_config(config), encoding="utf-8")
    return box


def test_compose_argv_roots_at_box_dir() -> None:
    assert compose_argv(Path("/opt/vibedpn"), "up", "-d") == [
        "docker",
        "compose",
        "--project-directory",
        "/opt/vibedpn",
        "up",
        "-d",
    ]
    assert compose_argv(Path("/b"), "down", all_profiles=True)[4:] == ["--profile", "*", "down"]


def test_check_box_requires_checkout_and_config(tmp_path: Path) -> None:
    with pytest.raises(ComposeError, match=r"install\.sh"):
        check_box(tmp_path)
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    with pytest.raises(ComposeError, match="vibedpn init"):
        check_box(tmp_path)
    (tmp_path / "config.yaml").write_text("version: 1\nrole: vps\n", encoding="utf-8")
    with pytest.raises(ComposeError, match="invalid"):
        check_box(tmp_path)


def test_check_box_and_refresh_env(tmp_path: Path) -> None:
    box = make_box(tmp_path)
    (box / ".env").write_text("VIBEDPN_TAG=v0.3.0\nCOMPOSE_PROFILES=stale\n", encoding="utf-8")
    config = check_box(box)
    assert config.role is Role.VPS
    refresh_env(box, config)
    text = (box / ".env").read_text(encoding="utf-8")
    assert "COMPOSE_PROFILES=provider,wg-server\n" in text
    assert "VIBEDPN_TAG=v0.3.0\n" in text
    assert "stale" not in text


def test_parse_ps_accepts_ndjson_and_arrays() -> None:
    ndjson = (
        '{"Service":"core","State":"running","Health":"healthy","Status":"Up 5s (healthy)"}\n'
        '{"Service":"ui","State":"exited","Health":"","Status":"Exited (1)"}\n'
    )
    assert parse_ps(ndjson) == [
        ServiceStatus("core", "running", "healthy", "Up 5s (healthy)"),
        ServiceStatus("ui", "exited", "-", "Exited (1)"),
    ]
    assert parse_ps('[{"Service":"core","State":"running"}]') == [
        ServiceStatus("core", "running", "-", "")
    ]
    assert parse_ps("") == []


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        ("permission denied while trying to connect to the Docker daemon socket", "docker group"),
        ("Cannot connect to the Docker daemon at unix:///var/run/docker.sock", "systemctl start"),
        ("something odd", "not usable"),
    ],
)
def test_preflight_maps_docker_errors(
    monkeypatch: pytest.MonkeyPatch, stderr: str, expected: str
) -> None:
    def failing(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=1, stderr=stderr, stdout="")

    monkeypatch.setattr(subprocess, "run", failing)
    with pytest.raises(ComposeError, match=expected):
        preflight()


def test_preflight_and_run_report_missing_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError("docker")

    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(ComposeError, match=r"install\.sh"):
        preflight()
    with pytest.raises(ComposeError, match=r"install\.sh"):
        compose.run(["docker"])
    with pytest.raises(ComposeError, match=r"install\.sh"):
        compose.capture(["docker"])
