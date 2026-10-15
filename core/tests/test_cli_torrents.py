"""vibedpn torrents ..., `init --torrents`, and what `up` does for the client."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vibedpn import cli
from vibedpn.bootstrap import render_config, required_secrets
from vibedpn.config import Config, load_config
from vibedpn.engine.apply import STORAGE_SCAN, read_task_result, request_task
from vibedpn.engine.storage import DEVICES_FILE, StorageError, parse_lsblk

from .conftest import client_config
from .test_cli_compose import Recorder
from .test_storage import LISTING
from .test_torrents_host import DISK

runner = CliRunner()


def make_box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: dict[str, object]) -> Recorder:
    recorder = Recorder()
    monkeypatch.setattr(cli, "run", recorder.run)
    monkeypatch.setattr(cli, "capture", recorder.capture)
    monkeypatch.setattr(cli, "preflight", lambda: None)
    monkeypatch.setattr(cli, "list_devices", lambda: parse_lsblk(LISTING))
    monkeypatch.setattr(cli, "SYSTEMD_DIR", tmp_path / "units")
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    config = Config.model_validate(raw)
    (tmp_path / "config.yaml").write_text(render_config(config), encoding="utf-8")
    (tmp_path / "secrets").mkdir(mode=0o700)
    for name in required_secrets(config):
        (tmp_path / "secrets" / name).write_text("x\n", encoding="utf-8")
    (tmp_path / "data" / "core").mkdir(parents=True)
    return recorder


def invoke(tmp_path: Path, *args: str) -> tuple[int, str]:
    result = runner.invoke(cli.app, [*args, "--dir", str(tmp_path)])
    return result.exit_code, result.output


def test_enable_turns_the_client_on_and_makes_its_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_box(tmp_path, monkeypatch, client_config())
    code, out = invoke(tmp_path, "torrents", "enable")
    assert code == 0, out
    assert load_config(tmp_path / "config.yaml").torrents.enabled
    password = tmp_path / "secrets" / "transmission-rpc-pass"
    assert (
        len(password.read_text(encoding="utf-8")) >= 32
        and oct(password.stat().st_mode)[-3:] == "600"
    )
    assert "127.0.0.1 only" in out
    keep = password.read_text(encoding="utf-8")
    invoke(tmp_path, "torrents", "enable")
    assert password.read_text(encoding="utf-8") == keep  # never replaced: the client holds it


def test_disable_keeps_the_rest_of_the_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_box(tmp_path, monkeypatch, client_config())
    invoke(tmp_path, "torrents", "enable")
    invoke(tmp_path, "torrents", "egress", "vps")
    code, out = invoke(tmp_path, "torrents", "disable")
    assert code == 0 and "downloads stay" in out
    torrents = load_config(tmp_path / "config.yaml").torrents
    assert (torrents.enabled, torrents.egress) == (False, "vps")


def test_egress_names_a_channel_the_box_has(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_box(tmp_path, monkeypatch, client_config())
    invoke(tmp_path, "torrents", "enable")
    code, out = invoke(tmp_path, "torrents", "egress", "dpn")
    assert code == 1 and "not an enabled uplink" in out
    assert load_config(tmp_path / "config.yaml").torrents.egress == "direct"
    assert invoke(tmp_path, "torrents", "egress", "vps")[0] == 0
    assert invoke(tmp_path, "torrents", "egress", "direct")[0] == 0


def test_a_vps_has_no_torrents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_box(
        tmp_path,
        monkeypatch,
        {"version": 1, "role": "vps", "wg_server": {"endpoint": "vps.example.com"}},
    )
    code, out = invoke(tmp_path, "torrents", "enable")
    assert code != 0, out


def test_show_tells_where_the_downloads_go_and_whether_the_disk_is_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_box(tmp_path, monkeypatch, client_config())
    invoke(tmp_path, "torrents", "enable")
    code, out = invoke(tmp_path, "torrents", "show")
    assert code == 0 and "enabled" in out and "the system disk" in out and "direct" in out
    invoke(tmp_path, "torrents", "storage", "use", "1234-ABCD")
    out = invoke(tmp_path, "torrents", "show")[1]
    assert "1234-ABCD (exfat), mounted" in out  # the listing of the test has it at its place
    monkeypatch.setattr(cli, "list_devices", lambda: [DISK])
    assert "NOT mounted" in invoke(tmp_path, "torrents", "show")[1]

    def broken() -> None:
        raise StorageError("lsblk not found")

    monkeypatch.setattr(cli, "list_devices", broken)
    assert "not checked: lsblk not found" in invoke(tmp_path, "torrents", "show")[1]


def test_storage_list_shows_what_can_be_used_and_why_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_box(tmp_path, monkeypatch, client_config())
    code, out = invoke(tmp_path, "torrents", "storage", "list")
    assert code == 0, out
    lines = {line.split()[0]: line for line in out.splitlines() if line[:1].isalnum()}
    assert "mounted here" in lines["1234-ABCD"]
    assert "system disk" in lines["6f8c1f0e-1b9d-4c53-8a0b-3d5a0f8e2c11"]
    assert "vfat is not supported" in lines["7A3B-91C2"]
    assert "01D6A5B3C4D5E6F7" in lines and "TORRENTS" in lines["1234-ABCD"]


def test_use_and_clear_move_the_downloads_between_disks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_box(tmp_path, monkeypatch, client_config())
    code, out = invoke(tmp_path, "torrents", "storage", "use", "01D6A5B3C4D5E6F7")
    assert code == 0, out
    torrents = load_config(tmp_path / "config.yaml").torrents
    assert (torrents.storage.uuid, torrents.storage.fstype) == ("01D6A5B3C4D5E6F7", "ntfs")
    assert torrents.download_dir == "/srv/vibedpn/usb/downloads"
    code, out = invoke(tmp_path, "torrents", "storage", "clear")
    assert code == 0, out
    torrents = load_config(tmp_path / "config.yaml").torrents
    assert torrents.storage.uuid is None and torrents.download_dir == "/srv/vibedpn/downloads"


@pytest.mark.parametrize(
    ("uuid", "why"),
    [
        ("FFFF-FFFF", "no disk with UUID"),
        ("6f8c1f0e-1b9d-4c53-8a0b-3d5a0f8e2c11", "the disk of the system"),
        ("7A3B-91C2", "vfat is not supported"),
    ],
)
def test_a_disk_that_cannot_be_used_is_refused_before_the_config_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uuid: str, why: str
) -> None:
    make_box(tmp_path, monkeypatch, client_config())
    code, out = invoke(tmp_path, "torrents", "storage", "use", uuid)
    assert code == 1 and why in out
    assert load_config(tmp_path / "config.yaml").torrents.storage.uuid is None


def test_the_look_the_panel_asked_for_is_kept_for_core(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_box(tmp_path, monkeypatch, client_config())
    data = tmp_path / "data" / "core"
    request_task(data, STORAGE_SCAN, 100.0, "storage")
    code, out = invoke(tmp_path, "torrents", "storage", "scan", "--requested")
    assert code == 0, out
    report = json.loads((data / DEVICES_FILE).read_text(encoding="utf-8"))
    assert {item["uuid"] for item in report["devices"]} >= {"1234-ABCD", "01D6A5B3C4D5E6F7"}
    result = read_task_result(data, STORAGE_SCAN)
    assert result is not None and result.ok and result.message == "6 disks"
    (data / DEVICES_FILE).unlink()
    invoke(tmp_path, "torrents", "storage", "scan", "--requested")  # already answered: no new look
    assert not (data / DEVICES_FILE).exists()


# --- up ---------------------------------------------------------------------------------------


def up_box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: dict[str, object]) -> Recorder:
    recorder = make_box(tmp_path, monkeypatch, raw)
    monkeypatch.setattr(cli, "find_tool", lambda name: f"/bin/{name}")
    monkeypatch.setattr("os.geteuid", lambda: 0)
    monkeypatch.setattr("os.chown", lambda *_args: None)
    monkeypatch.setattr("os.fchown", lambda *_args: None)
    monkeypatch.setattr(cli, "_ensure_apply_units", lambda _box: None)
    monkeypatch.setattr(cli, "_record_revision", lambda _box: None)
    monkeypatch.setattr(cli, "_record_services", lambda _box: None)
    monkeypatch.setattr(cli, "_reread", lambda _config: None)
    return recorder


def profiles(tmp_path: Path) -> list[str]:
    env = (tmp_path / ".env").read_text(encoding="utf-8")
    line = next(item for item in env.splitlines() if item.startswith("COMPOSE_PROFILES="))
    return line.removeprefix("COMPOSE_PROFILES=").split(",")


def test_up_prepares_the_client_before_compose_starts_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    box = tmp_path / "box"
    box.mkdir()
    raw = {**client_config(), "torrents": {"enabled": True, "download_dir": str(tmp_path / "dl")}}
    recorder = up_box(box, monkeypatch, raw)
    code, out = invoke(box, "up")
    assert code == 0, out
    assert (tmp_path / "dl" / "complete").is_dir()
    settings = box / "data" / "transmission" / "config" / "settings.json"
    assert json.loads(settings.read_text(encoding="utf-8"))["rpc-bind-address"] == "127.0.0.1"
    assert "torrents" in profiles(box)
    assert f"VIBEDPN_TORRENTS_DIR={tmp_path / 'dl'}" in (box / ".env").read_text("utf-8")
    assert any(call[-3:] == ["up", "-d", "--remove-orphans"] for call in recorder.calls)


def test_up_without_the_disk_starts_the_box_and_not_the_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = {
        **client_config(),
        "torrents": {
            "enabled": True,
            "download_dir": "/srv/vibedpn/usb/downloads",
            "storage": {"uuid": "1234-ABCD", "fstype": "exfat"},
        },
    }
    recorder = up_box(tmp_path, monkeypatch, raw)
    monkeypatch.setattr(cli, "list_devices", lambda: [DISK])  # plugged in, not mounted
    code, out = invoke(tmp_path, "up")
    assert code == 0, out
    assert "is not mounted" in out
    assert "torrents" not in profiles(tmp_path)
    assert any(call[-3:] == ["up", "-d", "--remove-orphans"] for call in recorder.calls)
    assert (tmp_path / "units" / "srv-vibedpn-usb.mount").is_file()


def test_up_with_the_client_off_leaves_no_unit_and_no_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    up_box(tmp_path, monkeypatch, client_config())
    assert invoke(tmp_path, "up")[0] == 0
    assert "torrents" not in profiles(tmp_path)
    assert not (tmp_path / "units").exists()
    assert not (tmp_path / "data" / "transmission").exists()
