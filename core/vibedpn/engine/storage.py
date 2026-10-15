"""The download disk of the torrent client: block devices, and the systemd unit that mounts one.

The host mounts the disk the owner picked (``torrents.storage``) by the UUID of its filesystem at
a fixed place, with a native ``.mount`` unit marked ``nofail``: a box that boots without its disk
still boots (docs/knowledge/transmission/storage.md). Everything here but the calls that run a
program is pure and tested on a real ``lsblk`` listing.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from vibedpn.config import TORRENTS_FILESYSTEMS, TORRENTS_USB_MOUNTPOINT, Config
from vibedpn.detect import find_tool
from vibedpn.engine.transmission import TRANSMISSION_UID

SYSTEMD_DIR = Path("/etc/systemd/system")
LSBLK_ARGS = [
    "-J",
    "-b",
    "-o",
    "NAME,PATH,UUID,LABEL,FSTYPE,SIZE,TYPE,MOUNTPOINTS",
]
# Filesystems that hold no files: nothing to pick as a download disk, nothing to show
NOT_DATA_FILESYSTEMS = frozenset(
    {"swap", "LVM2_member", "crypto_LUKS", "linux_raid_member", "squashfs", "iso9660"}
)
BLOCK_TYPES = frozenset({"disk", "part", "crypt", "lvm", "raid1"})
# The disk the system lives on is never offered: mounting it again is not what anyone means
SYSTEM_MOUNTPOINTS = ("/", "/boot", "/boot/firmware", "/home", "/var", "/usr")
# The facts about a disk that is unplugged now: the file the host leaves for core
DEVICES_FILE = "storage-devices.json"
DROPIN_NAME = "vibedpn-storage.conf"
DOCKER_UNIT = "docker.service"


class StorageError(RuntimeError):
    """The disks could not be listed or the mount could not be set up."""


@dataclass(frozen=True)
class BlockDevice:
    uuid: str
    label: str | None
    fstype: str
    size: int
    device: str
    mountpoints: tuple[str, ...]

    @property
    def system(self) -> bool:
        return any(point in SYSTEM_MOUNTPOINTS for point in self.mountpoints)

    @property
    def supported(self) -> bool:
        return self.fstype in TORRENTS_FILESYSTEMS and not self.system

    @property
    def mounted_here(self) -> bool:
        return TORRENTS_USB_MOUNTPOINT in self.mountpoints


def unit_name(path: str) -> str:
    """The name of the mount unit of ``path`` (systemd.unit(5) escaping, for the characters a
    path of ``torrents`` may hold): '/' becomes '-', a '-' inside a name becomes ``\\x2d``."""
    parts = [part.replace("-", "\\x2d") for part in path.strip("/").split("/")]
    return "-".join(parts) + ".mount"


MOUNT_UNIT = unit_name(TORRENTS_USB_MOUNTPOINT)


def parse_lsblk(text: str) -> list[BlockDevice]:
    """The devices of ``lsblk -J`` that hold a filesystem the owner could use, in listing order
    (children after their parent). A device with no UUID cannot be told apart after a replug and
    is left out."""
    try:
        tree = json.loads(text)
    except ValueError as exc:
        raise StorageError("lsblk printed no JSON") from exc
    nodes = tree.get("blockdevices") if isinstance(tree, dict) else None
    if not isinstance(nodes, list):
        raise StorageError("lsblk printed no blockdevices")
    found: list[BlockDevice] = []

    def walk(items: list[object]) -> None:
        for item in items:
            if not isinstance(item, dict):
                continue
            device = _device(item)
            if device is not None:
                found.append(device)
            children = item.get("children")
            if isinstance(children, list):
                walk(children)

    walk(nodes)
    return found


def _device(item: dict[str, object]) -> BlockDevice | None:
    uuid, fstype, path, size = (
        item.get("uuid"),
        item.get("fstype"),
        item.get("path"),
        item.get("size"),
    )
    if item.get("type") not in BLOCK_TYPES or fstype in NOT_DATA_FILESYSTEMS:
        return None
    if not (isinstance(uuid, str) and isinstance(fstype, str) and isinstance(path, str)):
        return None
    label = item.get("label")
    points = item.get("mountpoints")
    return BlockDevice(
        uuid=uuid,
        label=label if isinstance(label, str) else None,
        fstype=fstype,
        size=size if isinstance(size, int) else 0,
        device=path,
        mountpoints=tuple(p for p in points if isinstance(p, str))
        if isinstance(points, list)
        else (),
    )


def find_device(devices: list[BlockDevice], uuid: str) -> BlockDevice | None:
    """The device with this filesystem UUID; blkid prints hex in the case the filesystem has it,
    so the comparison is case-insensitive."""
    wanted = uuid.lower()
    return next((item for item in devices if item.uuid.lower() == wanted), None)


def mount_type_and_options(fstype: str) -> tuple[str, str]:
    """The ``Type=`` and ``Options=`` of the unit. exfat and ntfs3 have no owners on disk, so the
    mount hands every file to the client's uid; ext4 keeps its own and the host chowns the folder.
    ``nofail`` keeps the unit out of local-fs.target: a missing disk must not stop the boot
    (systemd.mount(5))."""
    owner = f"uid={TRANSMISSION_UID},gid={TRANSMISSION_UID},umask=002"
    return {
        "ext4": ("ext4", "noatime,nofail"),
        "exfat": ("exfat", f"noatime,nofail,{owner}"),
        "ntfs": ("ntfs3", f"noatime,nofail,{owner}"),
    }[fstype]


def render_mount_unit(uuid: str, fstype: str) -> str:
    mount_type, options = mount_type_and_options(fstype)
    return (
        "[Unit]\n"
        f"Description=VibeDPN: the download disk {uuid}\n\n"
        "[Mount]\n"
        f"What=/dev/disk/by-uuid/{uuid}\n"
        f"Where={TORRENTS_USB_MOUNTPOINT}\n"
        f"Type={mount_type}\n"
        f"Options={options}\n\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def render_docker_dropin() -> str:
    """Docker starts after the disk had its chance: a container whose bind source is not mounted
    yet does not start at all. ``Wants=`` and not ``Requires=``: a missing disk does not hold
    Docker back."""
    return f"[Unit]\nWants={MOUNT_UNIT}\nAfter={MOUNT_UNIT}\n"


def wanted_unit(config: Config) -> tuple[str, str] | None:
    """``(uuid, fstype)`` of the disk this configuration mounts, or ``None``."""
    storage = config.torrents.storage
    if not config.torrents.enabled or storage.uuid is None or storage.fstype is None:
        return None
    return storage.uuid, storage.fstype


def storage_mounted(config: Config, devices: list[BlockDevice]) -> bool:
    """Whether the disk of ``torrents.storage`` is mounted at its place right now."""
    storage = config.torrents.storage
    if storage.uuid is None:
        return False
    device = find_device(devices, storage.uuid)
    return device is not None and device.mounted_here


def devices_report(devices: list[BlockDevice], now: float) -> str:
    """What the host leaves for core (``DEVICES_FILE``): the devices of the last look."""
    return (
        json.dumps(
            {
                "scanned_at": now,
                "devices": [
                    {
                        "uuid": item.uuid,
                        "label": item.label,
                        "fstype": item.fstype,
                        "size": item.size,
                        "device": item.device,
                        "mountpoint": TORRENTS_USB_MOUNTPOINT
                        if item.mounted_here
                        else (item.mountpoints[0] if item.mountpoints else None),
                        "supported": item.supported,
                    }
                    for item in devices
                ],
            },
            ensure_ascii=False,
        )
        + "\n"
    )


def list_devices() -> list[BlockDevice]:
    """The disks of this host as `lsblk` sees them."""
    lsblk = find_tool("lsblk")
    if lsblk is None:
        raise StorageError("lsblk not found (package util-linux)")
    try:
        done = subprocess.run(
            [lsblk, *LSBLK_ARGS], check=False, capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise StorageError(f"cannot run lsblk: {exc}") from exc
    if done.returncode != 0:
        raise StorageError(f"lsblk failed: {done.stderr.strip()}")
    return parse_lsblk(done.stdout)
