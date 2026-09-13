"""Private files written atomically: a temporary 600 file, fsync, rename, fsync of the directory.

A reader — the wg-server container, a home box admin copying a peer file — never sees a
half-written file, a file that was briefly readable by others, or, after a power cut, an empty one.
"""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

FILE_MODE = 0o600


def write_private(path: Path, content: str) -> bool:
    """Write ``content`` with mode 600; ``False`` when the file already says exactly that.

    The temporary file is created 600 in the same directory, flushed to disk and renamed over the
    target: an existing file is replaced, never truncated and rewritten in place, so its old mode
    never applies to the new content.
    """
    if path.is_file() and not path.is_symlink() and path.read_text(encoding="utf-8") == content:
        path.chmod(FILE_MODE)
        return False
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), FILE_MODE)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary).replace(path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    fsync_directory(path.parent)
    return True


def write_like(path: Path, content: str) -> bool:
    """Replace an existing file atomically, keeping its mode and owner; ``False`` when it already
    says exactly that. For files that are not secrets — ``config.yaml`` belongs to the person and
    is 644 — but must still never be seen half-written by core reading it at start.

    The temporary file lives next to the target, so the directory must be writable: the box
    directory is root's, and ``PermissionError`` then tells the caller to ask for sudo."""
    if path.read_text(encoding="utf-8") == content:
        return False
    current = path.stat()
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), stat.S_IMODE(current.st_mode))
            if os.geteuid() == 0:
                os.fchown(handle.fileno(), current.st_uid, current.st_gid)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary).replace(path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    fsync_directory(path.parent)
    return True


def fsync_directory(directory: Path) -> None:
    """Make a rename durable. ext4 flushes a rename onto an existing name early, but not one onto
    a new name — the very first server.key — so a power cut right after the first start could
    leave an empty key that core then refuses to replace."""
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
