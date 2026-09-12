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
    check_secrets,
    compose_argv,
    engine_too_old,
    parse_ps,
    preflight,
    refresh_env,
    stale_services,
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
    with pytest.raises(ComposeError, match=r"install\.sh") as excinfo:
        check_box(tmp_path)
    assert excinfo.value.hint == "run install.sh"
    assert "checkout" in excinfo.value.message and "install.sh" not in excinfo.value.message
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


def test_refresh_env_needs_only_the_file_to_be_writable(tmp_path: Path) -> None:
    box = make_box(tmp_path)
    (box / ".env").write_text("VIBEDPN_TAG=v1\n", encoding="utf-8")
    box.chmod(0o555)  # directory read-only, file still ours
    try:
        refresh_env(box, check_box(box))
        assert "COMPOSE_PROFILES=provider,wg-server" in (box / ".env").read_text(encoding="utf-8")
    finally:
        box.chmod(0o755)


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


@pytest.mark.parametrize("garbage", ["not json at all", "null", "[1, 2]", '{"a":1}\n<html>'])
def test_parse_ps_rejects_garbage_readably(garbage: str) -> None:
    with pytest.raises(ComposeError, match="unexpected"):
        parse_ps(garbage)


def test_stale_services_is_the_difference_of_profiles() -> None:
    every = "core\nadguard\nmyst-provider\nui\n"
    active = "core\nui\n"
    assert stale_services(every, active) == ["adguard", "myst-provider"]
    assert stale_services(every, every) == []


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        ("permission denied while trying to connect to the Docker daemon socket", "docker group"),
        ("dial unix /var/run/docker.sock: connect: permission denied", "docker group"),
        (
            "failed to connect to the docker API at unix:///var/run/docker.sock; check if the path"
            " is correct and if the daemon is running: dial unix /var/run/docker.sock: connect:"
            " no such file or directory",
            "systemctl start",
        ),
        (
            "Cannot connect to the Docker daemon: dial tcp 127.0.0.1:2375: connection refused",
            "systemctl start",
        ),
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


@pytest.mark.parametrize(
    ("version", "too_old"),
    [
        ("26.1.5+dfsg1", True),
        ("27.5.1", True),
        ("28.0.0", False),
        ("29.5.2", False),
        ("", False),
        ("dev", False),
    ],
)
def test_engine_floor(version: str, too_old: bool) -> None:
    assert engine_too_old(version) is too_old


def test_preflight_refuses_an_old_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    def old(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stderr="", stdout="26.1.5+dfsg1\n")

    monkeypatch.setattr(subprocess, "run", old)
    with pytest.raises(ComposeError, match=r"older than 28\.0\.0") as excinfo:
        preflight()
    assert "install.sh" in excinfo.value.hint


def test_check_secrets_blocks_only_definitely_missing_ones(tmp_path: Path) -> None:
    box = make_box(tmp_path)  # vps with provider: needs htpasswd and nodeui-pass
    config = check_box(box)
    with pytest.raises(ComposeError, match="missing htpasswd, nodeui-pass"):
        check_secrets(box, config)
    (box / "secrets").mkdir()
    (box / "secrets" / "htpasswd").write_text("admin:x\n", encoding="utf-8")
    node = box / "data" / "myst-provider"
    node.mkdir(parents=True)
    (node / "nodeui-pass").write_text("", encoding="utf-8")  # empty = absent for the node
    with pytest.raises(ComposeError, match="missing nodeui-pass"):
        check_secrets(box, config)
    (node / "nodeui-pass").write_text("$2b$x\n", encoding="utf-8")
    check_secrets(box, config)


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
