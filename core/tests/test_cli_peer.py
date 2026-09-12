"""`vibedpn peer add|export|list|rm` with core replaced by fakes."""

import stat
from datetime import UTC, datetime
from ipaddress import IPv4Address
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vibedpn import cli
from vibedpn.api import client as core_api
from vibedpn.api.client import CoreUnreachableError, PeerRequestError
from vibedpn.api.models import PeerFile, PeerView
from vibedpn.bootstrap import render_config
from vibedpn.config import Config

from .conftest import home_config, vps_config

runner = CliRunner()
PEER_TEXT = "[Interface]\nPrivateKey = SECRETKEY=\nAddress = 10.78.0.2/32\n"
PEER = PeerFile(name="dacha", address=IPv4Address("10.78.0.2"), config=PEER_TEXT)


def box(tmp_path: Path, raw: dict[str, object]) -> Path:
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    (tmp_path / "config.yaml").write_text(
        render_config(Config.model_validate(raw)), encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def vps_box(tmp_path: Path) -> Path:
    return box(tmp_path, vps_config())


def test_add_prints_the_file_its_qr_code_and_the_next_step(
    vps_box: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[int, str]] = []

    def fake_add(port: int, name: str) -> PeerFile:
        calls.append((port, name))
        return PEER

    monkeypatch.setattr(core_api, "add_peer", fake_add)
    result = runner.invoke(cli.app, ["peer", "add", "dacha", "--dir", str(vps_box)])
    assert result.exit_code == 0, result.output
    assert calls == [(4480, "dacha")]
    assert result.output.startswith(PEER_TEXT)
    assert any(block in result.output for block in ("█", "▀", "▄"))
    assert "sudo vibedpn init --role client --peer-config FILE" in result.output


def test_export_writes_a_private_file_and_does_not_print_the_key(
    vps_box: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(core_api, "export_peer", lambda _port, _name: PEER)
    out = tmp_path / "dacha.conf"
    result = runner.invoke(
        cli.app, ["peer", "export", "dacha", "--out", str(out), "--dir", str(vps_box)]
    )
    assert result.exit_code == 0, result.output
    assert out.read_text(encoding="utf-8") == PEER_TEXT
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    assert "SECRETKEY" not in result.output
    assert f"--peer-config {out}" in result.output

    again = runner.invoke(
        cli.app, ["peer", "export", "dacha", "--out", str(out), "--dir", str(vps_box)]
    )
    assert again.exit_code == 1 and "already exists" in again.output
    forced = runner.invoke(
        cli.app,
        ["peer", "export", "dacha", "--out", str(out), "--force", "--dir", str(vps_box)],
    )
    assert forced.exit_code == 0


def test_list_prints_the_table(vps_box: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    view = PeerView(
        name="dacha",
        address=IPv4Address("10.78.0.2"),
        public_key="pub",
        created=datetime(2026, 9, 12, tzinfo=UTC),
        latest_handshake=0,
        rx_bytes=0,
        tx_bytes=0,
    )
    monkeypatch.setattr(core_api, "list_peers", lambda _port: [view])
    result = runner.invoke(cli.app, ["peer", "list", "--dir", str(vps_box)])
    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[0].split()[0] == "NAME"
    assert "dacha" in result.output and "never" in result.output


def test_rm_asks_first(vps_box: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    removed: list[str] = []
    monkeypatch.setattr(core_api, "remove_peer", lambda _port, name: removed.append(name))
    declined = runner.invoke(cli.app, ["peer", "rm", "dacha", "--dir", str(vps_box)], input="n\n")
    assert declined.exit_code == 1 and removed == []
    confirmed = runner.invoke(cli.app, ["peer", "rm", "dacha", "--dir", str(vps_box)], input="y\n")
    assert confirmed.exit_code == 0 and removed == ["dacha"]
    unattended = runner.invoke(cli.app, ["peer", "rm", "dacha", "--yes", "--dir", str(vps_box)])
    assert unattended.exit_code == 0 and removed == ["dacha", "dacha"]
    assert "removed peer dacha" in unattended.output


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (CoreUnreachableError("refused"), "core is not running; start the box with `vibedpn up`"),
        (PeerRequestError("a peer named 'dacha' already exists"), "already exists"),
    ],
)
def test_core_failures_are_one_line(
    vps_box: Path, monkeypatch: pytest.MonkeyPatch, error: Exception, expected: str
) -> None:
    def fail(_port: int, _name: str) -> PeerFile:
        raise error

    monkeypatch.setattr(core_api, "add_peer", fail)
    result = runner.invoke(cli.app, ["peer", "add", "dacha", "--dir", str(vps_box)])
    assert result.exit_code == 1
    assert expected in result.output
    assert "Traceback" not in result.output


def test_peers_are_refused_off_the_vps(tmp_path: Path) -> None:
    home = box(tmp_path, home_config())
    result = runner.invoke(cli.app, ["peer", "list", "--dir", str(home)])
    assert result.exit_code == 1
    assert "tunnel peers live on the VPS; this box has role home" in result.output
