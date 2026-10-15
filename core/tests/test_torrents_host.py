"""What the host does for the client before it starts: folders, settings.json, the mount unit."""

import json
import tarfile
from pathlib import Path

import pytest

from vibedpn.config import TORRENTS_USB_DIR, Config, TorrentsStorage
from vibedpn.engine.backup import create_archive
from vibedpn.engine.storage import DROPIN_NAME, MOUNT_UNIT, BlockDevice
from vibedpn.engine.torrents import (
    TorrentsHostError,
    backup_exclusions,
    check_download_dir,
    known_device,
    prepare,
    sync_mount_unit,
)
from vibedpn.engine.transmission import SETTINGS_FILE, settings_keys

from .conftest import client_config

DISK = BlockDevice("1234-ABCD", "TORRENTS", "exfat", 10**12, "/dev/sda1", ())
MOUNTED = BlockDevice("1234-ABCD", "TORRENTS", "exfat", 10**12, "/dev/sda1", ("/srv/vibedpn/usb",))


@pytest.fixture
def as_root(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    """The host commands run as root; hand-overs to the client's uid are recorded, not done."""
    handed: list[tuple[str, int]] = []
    monkeypatch.setattr("os.geteuid", lambda: 0)
    monkeypatch.setattr("os.chown", lambda path, uid, _gid: handed.append((str(path), uid)))
    monkeypatch.setattr("os.fchown", lambda _fd, uid, _gid: handed.append(("settings", uid)))
    return handed


def box(downloads: Path, **section: object) -> Config:
    torrents = {"enabled": True, "download_dir": str(downloads), **section}
    return Config.model_validate({**client_config(), "torrents": torrents})


def with_disk(downloads: Path | None = None) -> Config:
    """A box with a download disk. A folder of a test cannot lie under the real mountpoint, so for
    one the disk is put in after validation, which the model checks for the folder."""
    storage = {"uuid": "1234-ABCD", "fstype": "exfat"}
    if downloads is None:
        return box(Path(TORRENTS_USB_DIR), storage=storage)
    config = box(downloads)
    torrents = config.torrents.model_copy(update={"storage": TorrentsStorage(**storage)})
    return config.model_copy(update={"torrents": torrents})


class Runner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> int:
        self.calls.append(argv[1:])
        return 0


def run_prepare(
    tmp_path: Path, config: Config, devices: list[BlockDevice] | None = None
) -> tuple[object, Runner, list[str]]:
    runner, stopped = Runner(), []
    prepared = prepare(
        tmp_path / "box",
        config,
        systemctl="/bin/systemctl",
        run=runner,
        devices=lambda: devices or [],
        stop_client=lambda: stopped.append("stop"),
        unit_dir=tmp_path / "units",
    )
    return prepared, runner, stopped


def test_the_folders_and_the_settings_are_made_once(tmp_path: Path) -> None:
    config = box(tmp_path / "downloads")
    (tmp_path / "box").mkdir()
    prepared, _, stopped = run_prepare(tmp_path, config)
    assert (tmp_path / "downloads" / "complete").is_dir()
    assert (tmp_path / "downloads" / "incomplete").is_dir()
    settings = tmp_path / "box" / "data" / "transmission" / "config" / SETTINGS_FILE
    written = json.loads(settings.read_text(encoding="utf-8"))
    assert written["rpc-bind-address"] == "127.0.0.1"
    assert oct(settings.stat().st_mode & 0o777) == "0o600"
    assert stopped == []  # nothing was running: there was no file
    assert prepared.notes == [f"wrote {settings}"]  # type: ignore[attr-defined]
    again, _, stopped = run_prepare(tmp_path, config)
    assert again.notes == [] and stopped == []  # type: ignore[attr-defined]


def test_a_running_client_is_stopped_before_its_file_changes(tmp_path: Path) -> None:
    (tmp_path / "box").mkdir()
    run_prepare(tmp_path, box(tmp_path / "downloads"))
    _, _, stopped = run_prepare(tmp_path, box(tmp_path / "downloads", peer_port=51999))
    assert stopped == ["stop"]  # the client rewrites the file at exit: it must not run meanwhile
    settings = tmp_path / "box" / "data" / "transmission" / "config" / SETTINGS_FILE
    assert json.loads(settings.read_text(encoding="utf-8"))["peer-port"] == 51999


def test_new_limits_reach_a_running_client_without_a_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "box").mkdir()
    run_prepare(tmp_path, box(tmp_path / "downloads"))
    pushed: list[Config] = []

    def push(_box: Path, config: Config) -> bool:
        pushed.append(config)
        return True

    monkeypatch.setattr("vibedpn.engine.torrents.push_limits", push)
    limited = box(tmp_path / "downloads", speed_limit_down=500)
    prepared, _, stopped = run_prepare(tmp_path, limited)
    assert stopped == [] and len(pushed) == 1  # set live: the client holds them ahead of its file
    assert prepared.notes == ["speed limits set in the running torrent client"]  # type: ignore[attr-defined]
    settings = tmp_path / "box" / "data" / "transmission" / "config" / SETTINGS_FILE
    assert "speed-limit-down" not in json.loads(settings.read_text(encoding="utf-8"))


def test_limits_go_into_the_file_when_no_client_is_there_to_take_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "box").mkdir()
    run_prepare(tmp_path, box(tmp_path / "downloads"))
    monkeypatch.setattr("vibedpn.engine.torrents.push_limits", lambda _box, _config: False)
    _, _, stopped = run_prepare(tmp_path, box(tmp_path / "downloads", speed_limit_up=80))
    assert stopped == []  # nothing runs that would write the file over ours
    settings = tmp_path / "box" / "data" / "transmission" / "config" / SETTINGS_FILE
    written = json.loads(settings.read_text(encoding="utf-8"))
    assert (written["speed-limit-up"], written["speed-limit-up-enabled"]) == (80, True)


def test_the_clients_own_keys_survive_the_new_values(tmp_path: Path) -> None:
    config = box(tmp_path / "downloads")
    directory = tmp_path / "box" / "data" / "transmission" / "config"
    directory.mkdir(parents=True)
    keys = {**settings_keys(config), "blocklist-enabled": True, "peer-port": 1}
    (directory / SETTINGS_FILE).write_text(json.dumps(keys), encoding="utf-8")
    run_prepare(tmp_path, config)
    written = json.loads((directory / SETTINGS_FILE).read_text(encoding="utf-8"))
    assert written["blocklist-enabled"] is True and written["peer-port"] == 51413


def test_downloads_inside_the_box_are_refused(tmp_path: Path) -> None:
    (tmp_path / "box").mkdir()
    with pytest.raises(TorrentsHostError, match="a backup would take the downloads"):
        check_download_dir(tmp_path / "box", box(tmp_path / "box" / "data" / "films"))
    check_download_dir(tmp_path / "box", box(tmp_path / "films"))


@pytest.mark.usefixtures("as_root")
def test_an_absent_disk_stops_the_client_and_not_the_box(tmp_path: Path) -> None:
    (tmp_path / "box").mkdir()
    prepared, runner, _ = run_prepare(tmp_path, with_disk(tmp_path / "usb"), [DISK])
    assert prepared.skip  # type: ignore[attr-defined]
    assert "is not mounted" in prepared.notes[-1]  # type: ignore[attr-defined]
    assert not (tmp_path / "usb").exists()  # nothing was made on the bare mountpoint
    assert not (tmp_path / "box" / "data").exists()
    assert ["start", MOUNT_UNIT] in runner.calls  # the unit was asked to mount it


def test_a_mounted_disk_lets_the_client_start(
    tmp_path: Path, as_root: list[tuple[str, int]]
) -> None:
    (tmp_path / "box").mkdir()
    prepared, _, _ = run_prepare(tmp_path, with_disk(tmp_path / "usb"), [MOUNTED])
    assert not prepared.skip  # type: ignore[attr-defined]
    assert (tmp_path / "usb" / "complete").is_dir()
    assert {uid for _, uid in as_root} == {7756}  # the folders and the file go to the client


@pytest.mark.usefixtures("as_root")
def test_the_units_follow_the_configuration(tmp_path: Path) -> None:
    runner, units = Runner(), tmp_path / "units"
    notes = sync_mount_unit(with_disk(), systemctl="/bin/systemctl", run=runner, unit_dir=units)
    assert (units / MOUNT_UNIT).is_file()
    assert (units / "docker.service.d" / DROPIN_NAME).is_file()
    assert ["daemon-reload"] in runner.calls and ["enable", MOUNT_UNIT] in runner.calls
    assert ["start", MOUNT_UNIT] in runner.calls and len(notes) == 1
    runner.calls.clear()
    assert (
        sync_mount_unit(with_disk(), systemctl="/bin/systemctl", run=runner, unit_dir=units) == []
    )
    assert ["daemon-reload"] not in runner.calls  # unchanged files: nothing to reload
    gone = sync_mount_unit(box(tmp_path), systemctl="/bin/systemctl", run=runner, unit_dir=units)
    assert not (units / MOUNT_UNIT).exists()
    assert not (units / "docker.service.d" / DROPIN_NAME).exists()
    assert ["disable", "--now", MOUNT_UNIT] in runner.calls and len(gone) == 1


def test_a_box_that_never_had_a_disk_touches_no_unit(tmp_path: Path) -> None:
    runner = Runner()
    assert sync_mount_unit(box(tmp_path), systemctl=None, run=runner, unit_dir=tmp_path) == []
    assert runner.calls == []


def test_mounting_needs_systemd_and_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("os.geteuid", lambda: 1000)
    with pytest.raises(TorrentsHostError, match="needs systemd and root"):
        sync_mount_unit(with_disk(), systemctl="/bin/systemctl", run=Runner(), unit_dir=tmp_path)


def test_only_a_usable_listed_disk_can_be_picked() -> None:
    root = BlockDevice("aaaa-0000", None, "ext4", 1, "/dev/nvme0n1p2", ("/",))
    other = BlockDevice("bbbb-0000", None, "btrfs", 1, "/dev/sdb1", ())
    assert known_device([DISK, root, other], "1234-abcd") is DISK
    with pytest.raises(TorrentsHostError, match="no disk with UUID"):
        known_device([DISK], "ffff-ffff")
    with pytest.raises(TorrentsHostError, match="the disk of the system"):
        known_device([root], "aaaa-0000")
    with pytest.raises(TorrentsHostError, match="btrfs is not supported"):
        known_device([other], "bbbb-0000")


# --- the backup leaves the downloads out -----------------------------------------------------


def make_box_dir(root: Path) -> Path:
    for name in (
        "config.yaml",
        ".env",
        "secrets/transmission-rpc-pass",
        "data/transmission/config/settings.json",
        "data/transmission/downloads/complete/film.mkv",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    return root


def test_downloads_outside_the_box_are_not_in_the_archive_by_construction(tmp_path: Path) -> None:
    root = make_box_dir(tmp_path / "box")
    config = box(tmp_path / "downloads")
    assert backup_exclusions(root, config) == ()


def test_downloads_inside_the_box_are_excluded_explicitly(tmp_path: Path) -> None:
    root = make_box_dir(tmp_path / "box")
    config = box(root / "data" / "transmission" / "downloads")
    exclusions = backup_exclusions(root, config)
    assert exclusions == ("data/transmission/downloads",)
    create_archive(root, tmp_path / "plain.tar.gz")
    create_archive(root, tmp_path / "kept.tar.gz", exclusions)
    with tarfile.open(tmp_path / "plain.tar.gz") as plain:
        assert "data/transmission/downloads/complete/film.mkv" in plain.getnames()
    with tarfile.open(tmp_path / "kept.tar.gz") as kept:
        names = kept.getnames()
    assert not [name for name in names if "downloads" in name]
    assert (
        "data/transmission/config/settings.json" in names
    )  # the client's state is small: it stays
