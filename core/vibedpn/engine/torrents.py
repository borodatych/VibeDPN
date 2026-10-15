"""What the host does for the torrent client at `vibedpn up` and for `vibedpn torrents storage`.

Only the host sees Docker and systemd, so the files the client needs before it starts — the
folders, ``settings.json``, the mount unit of its disk — are made here and not by core. Every
step is idempotent and says what it did. Programs are run through ``run``/``lsblk`` parameters,
so the logic is tested without a host.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from vibedpn.atomic import write_private
from vibedpn.bootstrap import SECRETS_DIR
from vibedpn.config import Config
from vibedpn.engine.storage import (
    DOCKER_UNIT,
    DROPIN_NAME,
    MOUNT_UNIT,
    SYSTEMD_DIR,
    BlockDevice,
    StorageError,
    find_device,
    render_docker_dropin,
    render_mount_unit,
    storage_mounted,
    wanted_unit,
)
from vibedpn.engine.transmission import (
    COMPLETE_DIR,
    CONFIG_DIR,
    INCOMPLETE_DIR,
    SETTINGS_FILE,
    TRANSMISSION_UID,
    RpcClient,
    TransmissionError,
    limit_params,
    read_rpc_password,
    settings_differ,
    settings_text,
)


class TorrentsHostError(RuntimeError):
    """The host could not prepare the client; the message names the file and the remedy."""


Run = Callable[[list[str]], int]


@dataclass(frozen=True)
class TorrentsPrep:
    notes: list[str] = field(default_factory=list)
    # the client must not start: its disk is configured and not mounted (an empty folder of the
    # system disk would fill up silently)
    skip: bool = False


def inside(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def check_download_dir(box_dir: Path, config: Config) -> None:
    """The downloads stay out of the box directory: a backup takes ``data/`` whole, and a film
    in it would be in every archive."""
    download = Path(config.torrents.download_dir).resolve()
    if inside(download, box_dir.resolve()):
        raise TorrentsHostError(
            f"torrents.download_dir {config.torrents.download_dir} is inside {box_dir}:"
            " a backup would take the downloads; choose a folder outside it"
        )


def backup_exclusions(box_dir: Path, config: Config) -> tuple[str, ...]:
    """Paths of the box that a backup leaves out: the downloads, if their folder is inside it.
    Normally it is not (`up` refuses that), and the archive takes ``data/`` whole; the client's own
    state in ``data/transmission/config`` is small and stays in."""
    download = Path(config.torrents.download_dir).resolve()
    root = box_dir.resolve()
    if config.torrents.enabled and inside(download, root) and download != root:
        return (download.relative_to(root).as_posix(),)
    return ()


def _write_if_changed(path: Path, text: str) -> bool:
    try:
        if path.is_file() and path.read_text(encoding="utf-8") == text:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise TorrentsHostError(
            f"cannot write {path}: {exc.strerror or exc}; run with sudo?"
        ) from exc
    return True


def _remove(path: Path) -> bool:
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise TorrentsHostError(f"cannot remove {path}: {exc.strerror or exc}") from exc
    return True


def sync_mount_unit(
    config: Config, *, systemctl: str | None, run: Run, unit_dir: Path = SYSTEMD_DIR
) -> list[str]:
    """Make the units on the host what the configuration wants: the mount unit of the disk and
    the drop-in that makes Docker wait for it, or neither. Needs root and systemd."""
    wanted = wanted_unit(config)
    unit = unit_dir / MOUNT_UNIT
    dropin = unit_dir / f"{DOCKER_UNIT}.d" / DROPIN_NAME
    if wanted is None and not (unit.exists() or dropin.exists()):
        return []
    if systemctl is None or os.geteuid() != 0:
        if wanted is None:
            return []
        raise TorrentsHostError("mounting the download disk needs systemd and root: use sudo")
    notes: list[str] = []
    if wanted is None:
        run([systemctl, "disable", "--now", MOUNT_UNIT])
        removed = [_remove(unit), _remove(dropin)]
        if any(removed):
            run([systemctl, "daemon-reload"])
            notes.append("the download disk is no longer mounted by VibeDPN")
        return notes
    uuid, fstype = wanted
    changed = _write_if_changed(unit, render_mount_unit(uuid, fstype))
    changed = _write_if_changed(dropin, render_docker_dropin()) or changed
    if changed:
        run([systemctl, "daemon-reload"])
        notes.append(f"wrote {unit} and the Docker drop-in that waits for it")
    run([systemctl, "enable", MOUNT_UNIT])
    # a disk that is not there makes this fail, which is not an error of the box: nofail
    run([systemctl, "start", MOUNT_UNIT])
    return notes


def make_download_dirs(config: Config) -> None:
    base = Path(config.torrents.download_dir)
    for name in (COMPLETE_DIR, INCOMPLETE_DIR):
        folder = base / name
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if os.geteuid() == 0 and folder.stat().st_uid != TRANSMISSION_UID:
                os.chown(folder, TRANSMISSION_UID, TRANSMISSION_UID)
        except PermissionError:
            # exfat and ntfs3 give every file to the uid in the mount options; chown is refused
            if not folder.is_dir():
                raise TorrentsHostError(
                    f"cannot make {folder}: permission denied; run with sudo?"
                ) from None
        except OSError as exc:
            raise TorrentsHostError(f"cannot make {folder}: {exc.strerror or exc}") from exc


def push_limits(box_dir: Path, config: Config) -> bool:
    """Set the speed limits of config.yaml in the running client; ``False`` when it does not take
    them (not running, or the password is not the one it started with)."""
    try:
        client = RpcClient(read_rpc_password(box_dir / SECRETS_DIR))
        client.call("session_set", limit_params(config))
    except TransmissionError:
        return False
    return True


def render_settings(box_dir: Path, config: Config, stop_client: Callable[[], None]) -> list[str]:
    """Write our keys into data/transmission/config/settings.json. The client rewrites the file at
    exit with what it holds, so a running one is stopped first and `up` starts it again.

    The speed limits are the exception: the client holds the ones the panel set ahead of its file
    and applies them live, so a difference in them alone is a call to the running client and no
    restart. The file takes them only when the client is not there to be called."""
    path = box_dir / CONFIG_DIR / SETTINGS_FILE
    existing: str | None = None
    try:
        existing = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise TorrentsHostError(f"cannot read {path}: {exc.strerror or exc}") from exc
    if not settings_differ(existing, config):
        return []
    if existing is not None and not settings_differ(existing, config, limits=False):
        if push_limits(box_dir, config):
            return ["speed limits set in the running torrent client"]
    elif existing is not None:
        stop_client()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        owner = TRANSMISSION_UID if os.geteuid() == 0 else None
        write_private(path, settings_text(existing, config), owner=owner)
    except OSError as exc:
        raise TorrentsHostError(
            f"cannot write {path}: {exc.strerror or exc}; run with sudo?"
        ) from exc
    return [f"wrote {path}"]


def prepare(
    box_dir: Path,
    config: Config,
    *,
    systemctl: str | None,
    run: Run,
    devices: Callable[[], list[BlockDevice]],
    stop_client: Callable[[], None],
    unit_dir: Path = SYSTEMD_DIR,
) -> TorrentsPrep:
    """Everything the client needs before `docker compose up` starts it."""
    notes = sync_mount_unit(config, systemctl=systemctl, run=run, unit_dir=unit_dir)
    if not config.torrents.enabled:
        return TorrentsPrep(notes)
    check_download_dir(box_dir, config)
    if wanted_unit(config) is not None:
        try:
            mounted = storage_mounted(config, devices())
        except StorageError as exc:
            raise TorrentsHostError(str(exc)) from exc
        if not mounted:
            uuid = config.torrents.storage.uuid
            notes.append(
                f"the download disk {uuid} is not mounted: the torrent client does not start"
                " until it is connected and `vibedpn up` runs"
            )
            return TorrentsPrep(notes, skip=True)
    make_download_dirs(config)
    notes += render_settings(box_dir, config, stop_client)
    return TorrentsPrep(notes)


def known_device(devices: list[BlockDevice], uuid: str) -> BlockDevice:
    """The supported device with this UUID, or the reason there is none."""
    device = find_device(devices, uuid)
    if device is None:
        raise TorrentsHostError(f"no disk with UUID {uuid}: `vibedpn torrents storage list`")
    if not device.supported:
        why = "the disk of the system" if device.system else f"{device.fstype} is not supported"
        raise TorrentsHostError(f"disk {uuid} cannot be used: {why} (ext4, exfat, ntfs)")
    return device
