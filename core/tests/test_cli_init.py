"""``vibedpn init`` end to end with a fake host probe."""

from ipaddress import IPv4Address
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vibedpn import cli
from vibedpn.config import load_config
from vibedpn.detect import Interface

runner = CliRunner()


class FakeProbe:
    interface: Interface | None = Interface("eth0", IPv4Address("192.168.1.50"), 24)
    wireguard: bool | None = True

    def default_interface(self) -> Interface | None:
        return self.interface

    def wireguard_module_present(self) -> bool | None:
        return self.wireguard


@pytest.fixture(autouse=True)
def fake_probe(monkeypatch: pytest.MonkeyPatch) -> type[FakeProbe]:
    FakeProbe.interface = Interface("eth0", IPv4Address("192.168.1.50"), 24)
    FakeProbe.wireguard = True
    monkeypatch.setattr(cli, "HostProbe", FakeProbe)
    return FakeProbe


def test_init_vps_non_interactive(tmp_path: Path) -> None:
    result = runner.invoke(
        cli.app, ["init", "--role", "vps", "--endpoint", "203.0.113.7", "--dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert load_config(tmp_path / "config.yaml").role.value == "vps"
    assert "Next step: vibedpn up" in result.output
    assert not (tmp_path / "secrets" / "htpasswd").exists()


def test_init_client_with_flags(tmp_path: Path) -> None:
    peer = tmp_path / "home.conf"
    peer.write_text("[Interface]\n", encoding="utf-8")
    pw = tmp_path / "pw"
    pw.write_text("secret123\n", encoding="utf-8")
    result = runner.invoke(
        cli.app,
        [
            "init",
            "--role",
            "client",
            "--peer-config",
            str(peer),
            "--password-file",
            str(pw),
            "--dir",
            str(tmp_path / "box"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "box" / "secrets" / "wg-client.conf").is_file()
    assert (tmp_path / "box" / "secrets" / "htpasswd").is_file()


def test_init_interactive_home(tmp_path: Path) -> None:
    result = runner.invoke(
        cli.app, ["init", "--dir", str(tmp_path)], input="home\nsecret123\nsecret123\n"
    )
    assert result.exit_code == 0, result.output
    assert load_config(tmp_path / "config.yaml").role.value == "home"


def test_init_reasks_a_bad_password_interactively(tmp_path: Path) -> None:
    result = runner.invoke(
        cli.app,
        ["init", "--role", "home", "--dir", str(tmp_path)],
        input="short\nshort\n" + "п" * 37 + "\n" + "п" * 37 + "\nsecret123\nsecret123\n",
    )
    assert result.exit_code == 0, result.output
    assert "at least 8 characters long; try again" in result.output
    assert "72 bytes" in result.output
    assert (tmp_path / "secrets" / "htpasswd").is_file()


def test_init_rejects_long_password_file_before_writing(tmp_path: Path) -> None:
    pw = tmp_path / "pw"
    pw.write_text("п" * 37, encoding="utf-8")
    box = tmp_path / "box"
    result = runner.invoke(
        cli.app, ["init", "--role", "home", "--password-file", str(pw), "--dir", str(box)]
    )
    assert result.exit_code == 1
    assert "error: the password must be at most 72 bytes" in result.output
    assert not box.exists()


def test_init_rejects_bad_endpoint_flag_readably(tmp_path: Path) -> None:
    result = runner.invoke(
        cli.app,
        ["init", "--role", "vps", "--endpoint", "vps.example.com:51820", "--dir", str(tmp_path)],
    )
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "error: --endpoint:" in result.output and "without a port" in result.output


def test_init_reasks_a_bad_endpoint_interactively(tmp_path: Path) -> None:
    result = runner.invoke(
        cli.app,
        ["init", "--role", "vps", "--dir", str(tmp_path)],
        input="2001:db8::1\nvps.example.com\n",
    )
    assert result.exit_code == 0, result.output
    assert "try again" in result.output


def test_init_rejects_flags_of_another_role(tmp_path: Path) -> None:
    peer = tmp_path / "home.conf"
    peer.write_text("[Interface]\n", encoding="utf-8")
    result = runner.invoke(
        cli.app,
        ["init", "--role", "home", "--peer-config", str(peer), "--dir", str(tmp_path / "b")],
    )
    assert (
        result.exit_code == 1 and "--peer-config is only used with --role client" in result.output
    )
    result = runner.invoke(
        cli.app,
        ["init", "--role", "vps", "--password-file", str(peer), "--dir", str(tmp_path / "b")],
    )
    assert result.exit_code == 1 and "--password-file is not used with --role vps" in result.output
    result = runner.invoke(
        cli.app,
        ["init", "--role", "home", "--endpoint", "x.example.com", "--dir", str(tmp_path / "b")],
    )
    assert result.exit_code == 1 and "--endpoint is only used with --role vps" in result.output
    assert not (tmp_path / "b").exists()


def test_init_expands_tilde_in_peer_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "home.conf").write_text("[Interface]\n", encoding="utf-8")
    result = runner.invoke(
        cli.app,
        ["init", "--role", "client", "--dir", str(tmp_path / "box")],
        input="secret123\nsecret123\n~/nope.conf\n~/home.conf\n",
    )
    assert result.exit_code == 0, result.output
    assert "is not a file; try again" in result.output
    assert (tmp_path / "box" / "secrets" / "wg-client.conf").is_file()


def test_init_asks_endpoint_behind_nat(tmp_path: Path) -> None:
    result = runner.invoke(
        cli.app, ["init", "--role", "vps", "--dir", str(tmp_path)], input="vps.example.com\n"
    )
    assert result.exit_code == 0, result.output
    config = load_config(tmp_path / "config.yaml")
    assert config.wg_server is not None
    assert config.wg_server.endpoint == "vps.example.com"


def test_init_refuses_second_run_without_force_before_asking(tmp_path: Path) -> None:
    args = ["init", "--role", "vps", "--endpoint", "203.0.113.7", "--dir", str(tmp_path)]
    assert runner.invoke(cli.app, args).exit_code == 0
    again = runner.invoke(cli.app, ["init", "--dir", str(tmp_path)])  # no role: would prompt
    assert again.exit_code == 1
    assert "--force" in again.output
    assert "Role:" not in again.output
    forced = runner.invoke(cli.app, [*args, "--force"])
    assert forced.exit_code == 0, forced.output
    assert (tmp_path / "config.yaml.bak").is_file()


def test_init_warns_when_wireguard_cannot_be_checked(
    tmp_path: Path, fake_probe: type[FakeProbe]
) -> None:
    fake_probe.wireguard = None
    result = runner.invoke(
        cli.app, ["init", "--role", "vps", "--endpoint", "203.0.113.7", "--dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert "could not check the wireguard kernel module" in result.output


def test_init_warns_without_wireguard_module(tmp_path: Path, fake_probe: type[FakeProbe]) -> None:
    fake_probe.wireguard = False
    result = runner.invoke(
        cli.app, ["init", "--role", "vps", "--endpoint", "203.0.113.7", "--dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert "wireguard kernel module" in result.output


def test_init_fails_without_interface_before_asking_password(
    tmp_path: Path, fake_probe: type[FakeProbe]
) -> None:
    fake_probe.interface = None
    result = runner.invoke(cli.app, ["init", "--role", "home", "--dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "default route" in result.output
    assert "UI password" not in result.output
