"""Disks and the mount unit, on a listing in the shape of `lsblk -J -b` (util-linux 2.41)."""

import json
from pathlib import Path

import pytest

from vibedpn.config import Config
from vibedpn.engine.storage import (
    MOUNT_UNIT,
    StorageError,
    devices_report,
    find_device,
    mount_type_and_options,
    parse_lsblk,
    render_docker_dropin,
    render_mount_unit,
    storage_mounted,
    unit_name,
    wanted_unit,
)

from .conftest import client_config

LISTING = (Path(__file__).parent / "fixtures" / "lsblk.json").read_text(encoding="utf-8")


def test_only_disks_with_a_filesystem_and_an_id_are_listed() -> None:
    devices = parse_lsblk(LISTING)
    # no swap, no squashfs of a loop device, no bare disk, no disk without a UUID
    assert [item.uuid for item in devices] == [
        "AB12-CD34",
        "6f8c1f0e-1b9d-4c53-8a0b-3d5a0f8e2c11",
        "1234-ABCD",
        "01D6A5B3C4D5E6F7",
        "c0ffee00-1111-4222-8333-444455556666",
        "7A3B-91C2",
    ]


def test_the_system_disk_and_unknown_filesystems_are_not_offered() -> None:
    by_uuid = {item.uuid: item for item in parse_lsblk(LISTING)}
    assert by_uuid["1234-ABCD"].supported and by_uuid["1234-ABCD"].mounted_here
    assert by_uuid["01D6A5B3C4D5E6F7"].supported and not by_uuid["01D6A5B3C4D5E6F7"].mounted_here
    assert by_uuid["c0ffee00-1111-4222-8333-444455556666"].supported
    root = by_uuid["6f8c1f0e-1b9d-4c53-8a0b-3d5a0f8e2c11"]
    assert root.fstype == "ext4" and root.system and not root.supported
    assert not by_uuid["AB12-CD34"].supported  # the EFI partition: vfat, and /boot/efi
    assert not by_uuid["7A3B-91C2"].supported  # vfat is not one of the three


def test_both_shapes_of_an_empty_mountpoint_list_read_the_same() -> None:
    older = json.dumps(
        {
            "blockdevices": [
                {"name": "sda1", "path": "/dev/sda1", "uuid": "1234-ABCD", "fstype": "exfat"}
                | {"size": 5, "type": "part", "mountpoints": [None]}
            ]
        }
    )
    newer = older.replace("[null]", "[]")
    assert parse_lsblk(older) == parse_lsblk(newer)
    assert parse_lsblk(older)[0].mountpoints == ()


@pytest.mark.parametrize("text", ["", "[]", "{}", '{"blockdevices": 1}'])
def test_something_that_is_not_a_listing_is_an_error(text: str) -> None:
    with pytest.raises(StorageError):
        parse_lsblk(text)


def test_a_uuid_is_found_whatever_its_case() -> None:
    devices = parse_lsblk(LISTING)
    assert find_device(devices, "1234-abcd") is not None
    assert find_device(devices, "dead-beef") is None


def test_the_unit_is_named_after_the_mountpoint() -> None:
    assert MOUNT_UNIT == "srv-vibedpn-usb.mount"
    assert unit_name("/mnt/my-disk") == "mnt-my\\x2ddisk.mount"


def test_the_unit_mounts_by_uuid_with_nofail_and_the_right_type() -> None:
    text = render_mount_unit("1234-ABCD", "exfat")
    assert "What=/dev/disk/by-uuid/1234-ABCD\n" in text
    assert "Where=/srv/vibedpn/usb\n" in text
    assert "Type=exfat\n" in text
    assert "nofail" in text  # the unit stays out of local-fs.target: no disk, no stopped boot
    assert "uid=7756,gid=7756" in text  # a filesystem without owners hands its files to the client
    assert "WantedBy=multi-user.target" in text
    assert mount_type_and_options("ntfs")[0] == "ntfs3"
    ext4 = render_mount_unit("6f8c1f0e-1b9d-4c53-8a0b-3d5a0f8e2c11", "ext4")
    assert "Type=ext4\n" in ext4 and "uid=" not in ext4


def test_docker_waits_for_the_disk_without_depending_on_it() -> None:
    dropin = render_docker_dropin()
    assert f"Wants={MOUNT_UNIT}\n" in dropin and f"After={MOUNT_UNIT}\n" in dropin
    assert "Requires" not in dropin  # a missing disk must not hold Docker back


def test_the_mount_is_judged_by_the_uuid_and_the_place() -> None:
    devices = parse_lsblk(LISTING)
    on = Config.model_validate(
        {
            **client_config(),
            "torrents": {
                "enabled": True,
                "storage": {"uuid": "1234-abcd", "fstype": "exfat"},
                "download_dir": "/srv/vibedpn/usb/downloads",
            },
        }
    )
    assert wanted_unit(on) == ("1234-abcd", "exfat")
    assert storage_mounted(on, devices)
    elsewhere = on.model_copy(deep=True)
    elsewhere.torrents.storage.uuid = "01D6A5B3C4D5E6F7"  # plugged in, not mounted here
    assert not storage_mounted(elsewhere, devices)
    assert wanted_unit(Config.model_validate(client_config())) is None


def test_the_report_for_core_names_the_place_of_a_mounted_disk() -> None:
    report = json.loads(devices_report(parse_lsblk(LISTING), 1790000000.0))
    by_uuid = {item["uuid"]: item for item in report["devices"]}
    assert report["scanned_at"] == 1790000000.0
    assert by_uuid["1234-ABCD"]["mountpoint"] == "/srv/vibedpn/usb"
    assert by_uuid["01D6A5B3C4D5E6F7"]["mountpoint"] is None
    assert by_uuid["AB12-CD34"]["supported"] is False
