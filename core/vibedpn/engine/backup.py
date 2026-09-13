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
import tarfile
import time
from pathlib import Path, PurePosixPath

from vibedpn.bootstrap import CONFIG_FILE, DATA_DIR, ENV_FILE, SECRETS_DIR

BACKUP_MEMBERS = (CONFIG_FILE, ENV_FILE, SECRETS_DIR, DATA_DIR)
ARCHIVE_MODE = 0o600  # the archive holds secrets/
ASIDE_PREFIX = "restore-backup-"
BACKUPS_DIR = "backups"  # default place of `vibedpn backup` archives, inside the box
STAMP_FORMAT = "%Y%m%d-%H%M%S"


class BackupError(RuntimeError):
    """A user-facing reason why a backup or a restore did not happen."""


def stamp(now: float) -> str:
    return time.strftime(STAMP_FORMAT, time.localtime(now))


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
                tar.add(box_dir / name, arcname=name)
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
            check_members(tar.getmembers())
            if hasattr(tarfile, "tar_filter"):
                tar.extractall(box_dir, numeric_owner=True, filter="tar")
            else:
                tar.extractall(box_dir, numeric_owner=True)
    except (OSError, tarfile.TarError) as exc:
        raise BackupError(
            f"restore stopped: {exc}; the previous files are in {aside or 'place'}"
        ) from exc
    return aside
