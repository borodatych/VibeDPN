"""Backup and restore: what goes in, what an archive may not do, nothing of the owner is deleted."""

import io
import stat
import tarfile
from pathlib import Path

import pytest

from vibedpn.engine.backup import (
    ASIDE_PREFIX,
    BackupError,
    create_archive,
    read_members,
    restore_archive,
)

NOW = 1_789_000_000.0


def make_box(root: Path, marker: str) -> Path:
    box = root / "box"
    (box / "secrets").mkdir(parents=True)
    (box / "data" / "myst-provider" / "keystore").mkdir(parents=True)
    (box / "config.yaml").write_text(f"version: 1 # {marker}\n", encoding="utf-8")
    (box / ".env").write_text("VIBEDPN_TAG=next\n", encoding="utf-8")
    (box / "secrets" / "htpasswd").write_text(f"admin:{marker}\n", encoding="utf-8")
    (box / "data" / "myst-provider" / "keystore" / "key").write_text(marker, encoding="utf-8")
    (box / "compose.yaml").write_text("services: {}\n", encoding="utf-8")  # the checkout, not data
    return box


def test_the_archive_holds_the_box_state_privately(tmp_path: Path) -> None:
    box = make_box(tmp_path, "one")
    out = tmp_path / "backups" / "box.tar.gz"
    assert create_archive(box, out) == ["config.yaml", ".env", "secrets", "data"]
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    names = {member.name for member in read_members(out)}
    assert "data/myst-provider/keystore/key" in names and "compose.yaml" not in names
    with pytest.raises(BackupError, match="already exists"):
        create_archive(box, out)


def test_restore_moves_the_current_state_aside(tmp_path: Path) -> None:
    box = make_box(tmp_path, "old")
    out = tmp_path / "old.tar.gz"
    create_archive(box, out)
    (box / "secrets" / "htpasswd").write_text("admin:new\n", encoding="utf-8")
    aside = restore_archive(box, out, NOW)
    assert aside is not None and aside.name.startswith(ASIDE_PREFIX)
    assert (box / "secrets" / "htpasswd").read_text(encoding="utf-8") == "admin:old\n"
    assert (aside / "secrets" / "htpasswd").read_text(encoding="utf-8") == "admin:new\n"
    assert (box / "compose.yaml").exists()


def evil_archive(path: Path, member: tarfile.TarInfo, content: bytes = b"x") -> Path:
    with tarfile.open(path, mode="w:gz") as tar:
        config = tarfile.TarInfo("config.yaml")
        config.size = 1
        tar.addfile(config, io.BytesIO(b"x"))
        member.size = len(content) if member.isfile() else 0
        tar.addfile(member, io.BytesIO(content) if member.isfile() else None)
    return path


@pytest.mark.parametrize(
    ("name", "kind", "link", "reason"),
    [
        ("../escape", tarfile.REGTYPE, "", "outside the box"),
        ("/etc/passwd", tarfile.REGTYPE, "", "outside the box"),
        ("compose.yaml", tarfile.REGTYPE, "", "not part of a VibeDPN backup"),
        ("data/link", tarfile.SYMTYPE, "../../etc", "links outside"),
        ("data/abs", tarfile.SYMTYPE, "/etc/shadow", "links outside"),
        ("data/dev", tarfile.CHRTYPE, "", "device or a pipe"),
    ],
)
def test_a_hostile_archive_is_refused_before_anything_moves(
    tmp_path: Path, name: str, kind: bytes, link: str, reason: str
) -> None:
    box = make_box(tmp_path, "keep")
    member = tarfile.TarInfo(name)
    member.type = kind
    member.linkname = link
    archive = evil_archive(tmp_path / "evil.tar.gz", member)
    with pytest.raises(BackupError, match=reason):
        restore_archive(box, archive, NOW)
    assert (box / "secrets" / "htpasswd").read_text(encoding="utf-8") == "admin:keep\n"
    assert not list(box.glob(f"{ASIDE_PREFIX}*"))


def test_an_archive_without_config_is_not_a_backup(tmp_path: Path) -> None:
    archive = tmp_path / "other.tar.gz"
    with tarfile.open(archive, mode="w:gz") as tar:
        info = tarfile.TarInfo("data/x")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(BackupError, match=r"no config\.yaml"):
        read_members(archive)


def test_a_box_without_config_has_nothing_to_back_up(tmp_path: Path) -> None:
    with pytest.raises(BackupError, match="nothing to back up"):
        create_archive(tmp_path, tmp_path / "x.tar.gz")
