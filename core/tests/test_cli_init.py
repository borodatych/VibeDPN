"""``vibedpn init`` end to end with a fake host probe."""

from ipaddress import IPv4Address
from pathlib import Path

import bcrypt
import pytest
from typer.testing import CliRunner

from vibedpn import cli
from vibedpn.config import load_config
from vibedpn.detect import Interface
from vibedpn.engine.hostapd import HostapdError, check_passphrase

runner = CliRunner()


class FakeProbe:
    interface: Interface | None = Interface("eth0", IPv4Address("192.168.1.50"), 24)
    wireguard: bool | None = True
    memory: int | None = 8 * 1024**3

    def default_interface(self) -> Interface | None:
        return self.interface

    def is_wireless(self, name: str) -> bool:
        return name.startswith("wlan")

    def interfaces(self) -> list[Interface]:
        wifi = Interface("wlan0", IPv4Address("192.168.50.1"), 24)
        return [i for i in (self.interface, wifi) if i is not None]

    def wireguard_module_present(self) -> bool | None:
        return self.wireguard

    def ssh_ports(self) -> list[int]:
        return [22]

    def memory_bytes(self) -> int | None:
        return self.memory


@pytest.fixture(autouse=True)
def fake_probe(monkeypatch: pytest.MonkeyPatch) -> type[FakeProbe]:
    FakeProbe.interface = Interface("eth0", IPv4Address("192.168.1.50"), 24)
    FakeProbe.wireguard = True
    FakeProbe.memory = 8 * 1024**3
    monkeypatch.setattr(cli, "HostProbe", FakeProbe)
    return FakeProbe


def password_file(tmp_path: Path) -> Path:
    pw = tmp_path / "pw"
    pw.write_text("secret123\n", encoding="utf-8")
    return pw


def test_init_vps_non_interactive(tmp_path: Path) -> None:
    box = tmp_path / "box"
    result = runner.invoke(
        cli.app,
        [
            "init",
            "--role",
            "vps",
            "--endpoint",
            "203.0.113.7",
            "--password-file",
            str(password_file(tmp_path)),
            "--dir",
            str(box),
        ],
    )
    assert result.exit_code == 0, result.output
    assert load_config(box / "config.yaml").role.value == "vps"
    assert "Next step: vibedpn up" in result.output
    assert (box / "secrets" / "htpasswd").is_file()
    assert (box / "data" / "myst-provider" / "nodeui-pass").is_file()


def test_init_client_with_flags(tmp_path: Path) -> None:
    peer = tmp_path / "home.conf"
    peer.write_text("[Interface]\nPrivateKey = x\n\n[Peer]\nPublicKey = y\n", encoding="utf-8")
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
        input="secret123\nsecret123\n2001:db8::1\nvps.example.com\n",
    )
    assert result.exit_code == 0, result.output
    assert "try again" in result.output


def test_init_rejects_flags_of_another_role(tmp_path: Path) -> None:
    peer = tmp_path / "home.conf"
    peer.write_text("[Interface]\nPrivateKey = x\n\n[Peer]\nPublicKey = y\n", encoding="utf-8")
    result = runner.invoke(
        cli.app,
        ["init", "--role", "home", "--peer-config", str(peer), "--dir", str(tmp_path / "b")],
    )
    assert (
        result.exit_code == 1 and "--peer-config is only used with --role client" in result.output
    )
    result = runner.invoke(
        cli.app,
        ["init", "--role", "home", "--endpoint", "x.example.com", "--dir", str(tmp_path / "b")],
    )
    assert result.exit_code == 1 and "--endpoint is only used with --role vps" in result.output
    assert not (tmp_path / "b").exists()


def test_init_expands_tilde_in_peer_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "home.conf").write_text(
        "[Interface]\nPrivateKey = x\n\n[Peer]\nPublicKey = y\n", encoding="utf-8"
    )
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
        cli.app,
        ["init", "--role", "vps", "--dir", str(tmp_path)],
        input="secret123\nsecret123\nvps.example.com\n",
    )
    assert result.exit_code == 0, result.output
    config = load_config(tmp_path / "config.yaml")
    assert config.wg_server is not None
    assert config.wg_server.endpoint == "vps.example.com"


def test_init_refuses_second_run_without_force_before_asking(tmp_path: Path) -> None:
    box = tmp_path / "box"
    args = [
        "init",
        "--role",
        "vps",
        "--endpoint",
        "203.0.113.7",
        "--password-file",
        str(password_file(tmp_path)),
        "--dir",
        str(box),
    ]
    assert runner.invoke(cli.app, args).exit_code == 0
    again = runner.invoke(cli.app, ["init", "--dir", str(box)])  # no role: would prompt
    assert again.exit_code == 1
    assert "--force" in again.output
    assert "Role:" not in again.output
    forced = runner.invoke(cli.app, [*args, "--force"])
    assert forced.exit_code == 0, forced.output
    assert (box / "config.yaml.bak").is_file()


def test_init_warns_when_wireguard_cannot_be_checked(
    tmp_path: Path, fake_probe: type[FakeProbe]
) -> None:
    fake_probe.wireguard = None
    result = runner.invoke(
        cli.app,
        [
            "init",
            "--role",
            "vps",
            "--endpoint",
            "203.0.113.7",
            "--password-file",
            str(password_file(tmp_path)),
            "--dir",
            str(tmp_path / "box"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "could not check the wireguard kernel module" in result.output


def test_init_warns_without_wireguard_module(tmp_path: Path, fake_probe: type[FakeProbe]) -> None:
    fake_probe.wireguard = False
    result = runner.invoke(
        cli.app,
        [
            "init",
            "--role",
            "vps",
            "--endpoint",
            "203.0.113.7",
            "--password-file",
            str(password_file(tmp_path)),
            "--dir",
            str(tmp_path / "box"),
        ],
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
    assert cli.PANEL_PASSWORD_PROMPT not in result.output


def test_init_picks_the_panel_variant_by_memory_and_flag(
    tmp_path: Path, fake_probe: type[FakeProbe]
) -> None:
    fake_probe.memory = 2 * 1024**3
    small = tmp_path / "small"
    args = ["init", "--role", "home", "--password-file", str(password_file(tmp_path))]
    result = runner.invoke(cli.app, [*args, "--dir", str(small)])
    assert result.exit_code == 0, result.output
    assert load_config(small / "config.yaml").ui.variant.value == "lite"
    assert "Panel variant lite" in result.output
    forced = tmp_path / "forced"
    result = runner.invoke(cli.app, [*args, "--ui-variant", "full", "--dir", str(forced)])
    assert result.exit_code == 0, result.output
    assert load_config(forced / "config.yaml").ui.variant.value == "full"


def test_lan_interface_puts_the_box_in_gateway_mode(tmp_path: Path) -> None:
    result = runner.invoke(
        cli.app,
        [
            "init",
            "--dir",
            str(tmp_path),
            "--role",
            "home",
            "--lan-interface",
            "wlan0",
            "--password-file",
            str(password_file(tmp_path)),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Also wlan0: 192.168.50.1/24" in result.output
    network = load_config(tmp_path / "config.yaml").network
    assert network is not None and network.mode.value == "gateway"
    assert (network.lan_interface, network.wan_interface) == ("wlan0", "eth0")
    assert str(network.lan_address) == "192.168.50.1" and network.dhcp is not None
    assert (
        "COMPOSE_PROFILES=provider,consumer,router,dhcp,dns,ui" in (tmp_path / ".env").read_text()
    )


def test_lan_interface_without_an_address_is_refused(tmp_path: Path) -> None:
    result = runner.invoke(
        cli.app,
        [
            "init",
            "--dir",
            str(tmp_path),
            "--role",
            "home",
            "--lan-interface",
            "eth1",
            "--password-file",
            str(password_file(tmp_path)),
        ],
    )
    assert result.exit_code == 1
    assert (
        "LAN interface eth1 has no IPv4 address" in result.output
        and "wlan0 (192.168.50.1/24)" in result.output
    )
    assert not (tmp_path / "config.yaml").exists()


def test_a_vps_has_no_lan_interface(tmp_path: Path) -> None:
    result = runner.invoke(
        cli.app,
        [
            "init",
            "--dir",
            str(tmp_path),
            "--role",
            "vps",
            "--endpoint",
            "vps.example.com",
            "--lan-interface",
            "wlan0",
            "--password-file",
            str(password_file(tmp_path)),
        ],
    )
    assert result.exit_code == 1
    assert "--lan-interface is only used with --role home or client" in result.output


def init_home(tmp_path: Path, *extra: str) -> tuple[int, str]:
    result = runner.invoke(
        cli.app,
        [
            "init",
            "--dir",
            str(tmp_path),
            "--role",
            "home",
            *extra,
            "--password-file",
            str(password_file(tmp_path)),
        ],
    )
    return result.exit_code, result.output


def test_wifi_flags_make_an_access_point_with_a_generated_passphrase(tmp_path: Path) -> None:
    code, output = init_home(
        tmp_path, "--lan-interface", "wlan0", "--wifi-ssid", "Home net", "--wifi-country", "de"
    )
    assert code == 0, output
    assert "Wi-Fi 'Home net'" in output
    network = load_config(tmp_path / "config.yaml").network
    assert network is not None and network.wifi is not None
    assert (network.wifi.ssid, network.wifi.country) == ("Home net", "DE")
    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "router,dhcp,wifi,dns" in env
    passphrase = (tmp_path / "secrets" / "wifi-passphrase").read_text(encoding="utf-8")
    assert 8 <= len(passphrase) <= 63 and passphrase.isascii()
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    shown = runner.invoke(cli.app, ["wifi", "show", "--dir", str(tmp_path)])
    assert shown.exit_code == 0, shown.output
    assert "ssid: Home net" in shown.output and f"passphrase: {passphrase}" in shown.output


def test_wifi_needs_a_radio_and_both_flags(tmp_path: Path) -> None:
    code, output = init_home(tmp_path, "--wifi-ssid", "Home", "--wifi-country", "DE")
    assert code == 1 and "--wifi-ssid needs --lan-interface" in output
    code, output = init_home(tmp_path, "--lan-interface", "wlan0", "--wifi-ssid", "Home")
    assert code == 1 and "go together" in output
    FakeProbe.interface = Interface("wlan9", IPv4Address("192.168.1.50"), 24)
    code, output = init_home(
        tmp_path, "--lan-interface", "eth0", "--wifi-ssid", "Home", "--wifi-country", "DE"
    )
    assert code == 1 and "eth0 is not a wireless interface" in output
    assert not (tmp_path / "config.yaml").exists()


def test_wifi_show_on_a_box_without_wifi(tmp_path: Path) -> None:
    code, output = init_home(tmp_path)
    assert code == 0, output
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    shown = runner.invoke(cli.app, ["wifi", "show", "--dir", str(tmp_path)])
    assert shown.exit_code == 1 and "serves no Wi-Fi" in shown.output


class ComposeRecorder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, argv: list[str]) -> int:
        self.calls.append(argv)
        return 0


@pytest.fixture
def wifi_box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, ComposeRecorder]:
    code, output = init_home(
        tmp_path, "--lan-interface", "wlan0", "--wifi-ssid", "Home net", "--wifi-country", "DE"
    )
    assert code == 0, output
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    recorder = ComposeRecorder()
    monkeypatch.setattr(cli, "run", recorder.run)
    monkeypatch.setattr(cli, "preflight", lambda: None)
    return tmp_path, recorder


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("short", "8 to 63 characters, not 5"),
        ("x" * 64, "8 to 63 characters, not 64"),
        ("пароль-на-русском", "Latin letters"),
        (" padded passphrase", "cannot start or end with a space"),
    ],
)
def test_a_passphrase_hostapd_would_refuse_is_refused(value: str, reason: str) -> None:
    with pytest.raises(HostapdError, match=reason):
        check_passphrase(value)
    assert check_passphrase("my home wifi 2026!") == "my home wifi 2026!"


def test_wifi_passphrase_stores_what_the_owner_typed_and_restarts_the_access_point(
    wifi_box: tuple[Path, ComposeRecorder],
) -> None:
    box_dir, recorder = wifi_box
    result = runner.invoke(
        cli.app,
        ["wifi", "passphrase", "--dir", str(box_dir)],
        input="my home wifi 2026!\nmy home wifi 2026!\n",
    )
    assert result.exit_code == 0, result.output
    assert "my home wifi 2026!" not in result.output
    secret = box_dir / "secrets" / "wifi-passphrase"
    assert secret.read_text(encoding="utf-8") == "my home wifi 2026!"
    assert secret.stat().st_mode & 0o777 == 0o600
    assert [argv[-5:] for argv in recorder.calls] == [
        ["up", "-d", "--force-recreate", "core", "hostapd"]
    ]
    again = runner.invoke(
        cli.app,
        ["wifi", "passphrase", "--dir", str(box_dir)],
        input="my home wifi 2026!\nmy home wifi 2026!\n",
    )
    assert again.exit_code == 0 and "nothing to restart" in again.output
    assert len(recorder.calls) == 1


def test_wifi_passphrase_refuses_a_short_one_and_keeps_the_old(
    wifi_box: tuple[Path, ComposeRecorder],
) -> None:
    box_dir, recorder = wifi_box
    secret = box_dir / "secrets" / "wifi-passphrase"
    before = secret.read_text(encoding="utf-8")
    result = runner.invoke(
        cli.app, ["wifi", "passphrase", "--dir", str(box_dir)], input="short\nshort\n"
    )
    assert result.exit_code == 1 and "8 to 63 characters" in result.output
    assert secret.read_text(encoding="utf-8") == before and recorder.calls == []


def test_wifi_passphrase_on_a_box_without_wifi(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, output = init_home(tmp_path)
    assert code == 0, output
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setattr(cli, "preflight", lambda: None)
    result = runner.invoke(cli.app, ["wifi", "passphrase", "--dir", str(tmp_path)])
    assert result.exit_code == 1 and "serves no Wi-Fi" in result.output


def test_password_replaces_the_panel_and_node_hashes_and_restarts_the_node(
    wifi_box: tuple[Path, ComposeRecorder],
) -> None:
    box_dir, recorder = wifi_box
    result = runner.invoke(
        cli.app, ["password", "--dir", str(box_dir)], input="new-panel-pass\nnew-panel-pass\n"
    )
    assert result.exit_code == 0, result.output
    assert "new-panel-pass" not in result.output
    htpasswd = box_dir / "secrets" / "htpasswd"
    user, hashed = htpasswd.read_text(encoding="utf-8").strip().split(":", 1)
    assert user == "admin" and bcrypt.checkpw(b"new-panel-pass", hashed.encode("ascii"))
    node = box_dir / "data" / "myst-provider" / "nodeui-pass"
    assert bcrypt.checkpw(
        b"new-panel-pass", node.read_text(encoding="utf-8").strip().encode("ascii")
    )
    assert htpasswd.stat().st_mode & 0o777 == 0o600 and node.stat().st_mode & 0o777 == 0o600
    assert [argv[-4:] for argv in recorder.calls] == [
        ["up", "-d", "--force-recreate", "myst-provider"]
    ]


def test_password_asks_again_until_it_fits_the_policy(
    wifi_box: tuple[Path, ComposeRecorder],
) -> None:
    box_dir, _recorder = wifi_box
    before = (box_dir / "secrets" / "htpasswd").read_text(encoding="utf-8")
    result = runner.invoke(
        cli.app,
        ["password", "--dir", str(box_dir)],
        input="short\nshort\nlong-enough-1\nlong-enough-1\n",
    )
    assert result.exit_code == 0, result.output
    assert "at least" in result.output
    after = (box_dir / "secrets" / "htpasswd").read_text(encoding="utf-8")
    assert after != before and bcrypt.checkpw(
        b"long-enough-1", after.strip().split(":", 1)[1].encode()
    )
