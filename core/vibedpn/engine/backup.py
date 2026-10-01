"""Backup and restore of a box: config.yaml, .env, secrets/ and data/ in one tar.gz.

Taken on a stopped box (docs/decisions.md, decision 12): Postgres of the panel and the keystores of
the nodes are only consistent at rest. A restore never deletes what the box holds: the current
files move aside first. Every member is checked before anything is written, so an archive with an
absolute path, ``..`` or a link out of the box is refused whole. ``tarfile``'s own extraction filter
is used where it exists (Python 3.12, 3.11.4+); Debian bookworm ships 3.11.2 without it
(docs/knowledge/linux/boxBackup.md), so the checks here do not rely on it.
"""

from __future__ import annotations

import os
import re
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from pydantic import ValidationError

from vibedpn.bootstrap import CONFIG_FILE, DATA_DIR, ENV_FILE, SECRETS_DIR
from vibedpn.config import Config, parse_yaml
from vibedpn.engine.apply import BOX_DATA_DIR, TASKS
from vibedpn.engine.update import UPDATE

BACKUP_MEMBERS = (CONFIG_FILE, ENV_FILE, SECRETS_DIR, DATA_DIR)
ARCHIVE_MODE = 0o600  # the archive holds secrets/
ASIDE_PREFIX = "restore-backup-"
FAILED_PREFIX = "restore-failed-"
BACKUPS_DIR = "backups"  # default place of `vibedpn backup` archives, inside the box
STAMP_FORMAT = "%Y%m%d-%H%M%S"
# The archives the box makes and lists; nothing else in backups/ is shown, served or pruned
ARCHIVE_NAME = re.compile(r"^vibedpn-\d{8}-\d{6}\.tar\.gz$")
# The one place a restore asked in the panel reads from: an upload, or a listed archive copied there
RESTORE_SLOT = "restore-upload.tar.gz"
# What core and the host tell each other in data/core: the moment of a request and its result
# A copy of them in an archive would replay a backup or an update the moment it is restored
HANDSHAKE_MEMBERS = frozenset(
    str(BOX_DATA_DIR / name) for task in (*TASKS, UPDATE) for name in (task.request, task.result)
)


class BackupError(RuntimeError):
    """A user-facing reason why a backup or a restore did not happen."""


@dataclass(frozen=True)
class Archive:
    name: str
    size: int  # bytes
    created_at: float  # the time in its name, which the box wrote when it made the copy


def stamp(now: float) -> str:
    return time.strftime(STAMP_FORMAT, time.localtime(now))


def archive_name(now: float) -> str:
    return f"vibedpn-{stamp(now)}.tar.gz"


def list_archives(backups_dir: Path) -> list[Archive]:
    """The archives of the box, newest first; a missing directory has none"""
    try:
        entries = [entry for entry in backups_dir.iterdir() if ARCHIVE_NAME.match(entry.name)]
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise BackupError(f"cannot read {backups_dir}: {exc.strerror or exc}") from exc
    found = []
    for entry in sorted(entries, key=lambda item: item.name, reverse=True):
        moment = entry.name.removeprefix("vibedpn-").removesuffix(".tar.gz")
        created = time.mktime(time.strptime(moment, STAMP_FORMAT))
        try:
            found.append(Archive(entry.name, entry.stat().st_size, created))
        except FileNotFoundError:
            continue  # removed meanwhile
    return found


def prune_archives(backups_dir: Path, keep: int) -> list[str]:
    """Remove the oldest archives beyond ``keep``; returns the names removed"""
    removed = []
    for archive in list_archives(backups_dir)[keep:]:
        try:
            (backups_dir / archive.name).unlink(missing_ok=True)
        except OSError as exc:
            raise BackupError(f"cannot remove {archive.name}: {exc.strerror or exc}") from exc
        removed.append(archive.name)
    return removed


def _without_handshake(member: tarfile.TarInfo) -> tarfile.TarInfo | None:
    return None if member.name in HANDSHAKE_MEMBERS else member


def create_archive(box_dir: Path, out: Path) -> list[str]:
    """Write the archive of the box to ``out`` (mode 600); returns the top-level names it holds."""
    present = [name for name in BACKUP_MEMBERS if (box_dir / name).exists()]
    if CONFIG_FILE not in present:
        raise BackupError(f"{box_dir / CONFIG_FILE} is missing: nothing to back up")
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, ARCHIVE_MODE)
    except FileExistsError:
        raise BackupError(f"{out} already exists") from None
    except OSError as exc:
        raise BackupError(f"cannot create {out}: {exc.strerror or exc}") from exc
    try:
        with (
            os.fdopen(descriptor, "wb") as stream,
            tarfile.open(fileobj=stream, mode="w:gz") as tar,
        ):
            for name in present:
                tar.add(box_dir / name, arcname=name, filter=_without_handshake)
    except OSError as exc:
        out.unlink(missing_ok=True)
        raise BackupError(f"cannot write {out}: {exc.strerror or exc}") from exc
    return present


def check_members(members: list[tarfile.TarInfo]) -> None:
    """Refuse the archive when any member would land outside the box or is not a plain entry."""
    names = set()
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise BackupError(f"archive member {member.name!r} points outside the box")
        if path.parts[0] not in BACKUP_MEMBERS:
            raise BackupError(f"archive member {member.name!r} is not part of a VibeDPN backup")
        if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
            raise BackupError(f"archive member {member.name!r} is a device or a pipe")
        if member.issym() or member.islnk():
            target = PurePosixPath(member.linkname)
            resolved = target if member.islnk() else path.parent / target
            if target.is_absolute() or ".." in PurePosixPath(os.path.normpath(resolved)).parts:
                raise BackupError(f"archive member {member.name!r} links outside the box")
        names.add(path.parts[0])
    if CONFIG_FILE not in names:
        raise BackupError(f"the archive has no {CONFIG_FILE}: not a VibeDPN backup")


def read_members(archive: Path) -> list[tarfile.TarInfo]:
    try:
        with tarfile.open(archive, mode="r:gz") as tar:
            members = tar.getmembers()
    except (OSError, tarfile.TarError) as exc:
        raise BackupError(f"cannot read {archive}: {exc}") from exc
    check_members(members)
    return members


def archive_config(archive: Path) -> Config:
    """The configuration an archive would restore, checked by this version of the box: a restore
    that `up` cannot start is refused before anything moves"""
    read_members(archive)
    try:
        with tarfile.open(archive, mode="r:gz") as tar:
            member = tar.extractfile(CONFIG_FILE)
            if member is None:
                raise BackupError(f"the archive has no {CONFIG_FILE}: not a VibeDPN backup")
            text = member.read().decode("utf-8")
    except KeyError:
        raise BackupError(f"the archive has no {CONFIG_FILE}: not a VibeDPN backup") from None
    except (OSError, tarfile.TarError, UnicodeDecodeError) as exc:
        raise BackupError(f"cannot read {CONFIG_FILE} in {archive.name}: {exc}") from exc
    try:
        return Config.model_validate(parse_yaml(text))
    except (ValueError, ValidationError) as exc:
        raise BackupError(f"{CONFIG_FILE} in {archive.name} is not a valid box: {exc}") from exc


def restore_archive(box_dir: Path, archive: Path, now: float) -> Path | None:
    """Move the current files aside, then unpack; returns where they went (``None``: nothing)."""
    read_members(archive)
    present = [name for name in BACKUP_MEMBERS if (box_dir / name).exists()]
    aside = box_dir / f"{ASIDE_PREFIX}{stamp(now)}" if present else None
    try:
        if aside is not None:
            aside.mkdir(mode=0o700)
            for name in present:
                (box_dir / name).replace(aside / name)
        with tarfile.open(archive, mode="r:gz") as tar:
            members = tar.getmembers()
            check_members(members)
            kept = [member for member in members if member.name not in HANDSHAKE_MEMBERS]
            if hasattr(tarfile, "tar_filter"):
                tar.extractall(box_dir, members=kept, numeric_owner=True, filter="tar")
            else:
                tar.extractall(box_dir, members=kept, numeric_owner=True)
    except (OSError, tarfile.TarError) as exc:
        raise BackupError(
            f"restore stopped: {exc}; the previous files are in {aside or 'place'}"
        ) from exc
    return aside


def undo_restore(box_dir: Path, aside: Path | None, now: float) -> Path:
    """Put back the files a restore moved aside; the restored ones move to ``restore-failed-<time>``
    so nothing is deleted either way. Returns where the restored files went."""
    failed = box_dir / f"{FAILED_PREFIX}{stamp(now)}"
    try:
        failed.mkdir(mode=0o700)
        for name in BACKUP_MEMBERS:
            if (box_dir / name).exists():
                (box_dir / name).replace(failed / name)
        if aside is not None:
            for name in BACKUP_MEMBERS:
                if (aside / name).exists():
                    (aside / name).replace(box_dir / name)
            aside.rmdir()
    except OSError as exc:
        raise BackupError(
            f"cannot put the previous files back: {exc};"
            f" they are in {aside}, the restored ones in {failed}"
        ) from exc
    return failed
