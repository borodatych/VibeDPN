"""The archives of the box from the panel: list, download, delete, and the backup or restore the
host is asked for (api/backups.py)"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from vibedpn.api import backups as backups_module
from vibedpn.api.app import create_app
from vibedpn.bootstrap import render_config
from vibedpn.config import Config
from vibedpn.engine.apply import BACKUP, RESTORE, read_task_request, request_task
from vibedpn.engine.backup import RESTORE_SLOT, create_archive

from .conftest import home_config, vps_config

OLD = "vibedpn-20260101-000000.tar.gz"
NEW = "vibedpn-20260102-000000.tar.gz"


def archive_of(tmp_path: Path, raw: dict[str, Any], name: str) -> Path:
    source = tmp_path / f"source-{name}"
    source.mkdir()
    (source / "config.yaml").write_text(render_config(Config.model_validate(raw)), encoding="utf-8")
    target = tmp_path / name
    create_archive(source, target)
    return target


def box(tmp_path: Path) -> tuple[TestClient, Path, Path]:
    data = tmp_path / "data"
    backups = tmp_path / "backups"
    data.mkdir()
    backups.mkdir()
    for name in (OLD, NEW):
        archive_of(tmp_path, home_config(), name).replace(backups / name)
    (backups / "notes.txt").write_text("not an archive\n", encoding="utf-8")
    app = create_app(Config.model_validate(home_config()), data_dir=data, backups_dir=backups)
    return TestClient(app), data, backups


def test_the_archives_are_listed_served_and_removed_by_name_only(tmp_path: Path) -> None:
    client, _data, backups = box(tmp_path)
    listed = client.get("/backups").json()
    assert [item["name"] for item in listed["archives"]] == [NEW, OLD]  # newest first
    assert listed["keep"] == 10 and listed["backup"]["pending"] is False
    assert listed["archives"][0]["size"] == (backups / NEW).stat().st_size
    got = client.get(f"/backups/{NEW}")
    assert got.status_code == 200 and got.content == (backups / NEW).read_bytes()
    assert f'filename="{NEW}"' in got.headers["content-disposition"]
    for name in ("notes.txt", "..%2Fdata", "vibedpn-x.tar.gz"):
        assert client.get(f"/backups/{name}").status_code == 404
    assert client.delete(f"/backups/{OLD}").status_code == 204 and not (backups / OLD).exists()
    assert client.delete("/backups/notes.txt").status_code == 404


def test_a_backup_is_asked_of_the_host_one_at_a_time(tmp_path: Path) -> None:
    client, data, _backups = box(tmp_path)
    asked = client.post("/backups")
    assert asked.status_code == 200 and asked.json()["backup"]["pending"] is True
    assert read_task_request(data, BACKUP) is not None
    assert client.post("/backups").status_code == 409  # the box stops for it: one at a time
    assert client.post(f"/backups/{NEW}/restore").status_code == 409


def test_a_request_the_host_never_answered_blocks_nothing(tmp_path: Path) -> None:
    client, data, _backups = box(tmp_path)
    request_task(data, BACKUP, time.time() - BACKUP.timeout - 1, "long ago")
    state = client.get("/backups").json()["backup"]
    assert state["pending"] is False and state["ok"] is False
    assert client.post("/backups").status_code == 200


def test_a_listed_archive_goes_to_the_slot_and_the_host_is_asked(tmp_path: Path) -> None:
    client, data, backups = box(tmp_path)
    asked = client.post(f"/backups/{OLD}/restore")
    assert asked.status_code == 200 and asked.json()["restore"]["pending"] is True
    assert (backups / RESTORE_SLOT).read_bytes() == (backups / OLD).read_bytes()
    assert (backups / RESTORE_SLOT).stat().st_mode & 0o777 == 0o600  # it holds the secrets of a box
    assert read_task_request(data, RESTORE) is not None


def test_an_upload_is_checked_before_the_host_is_asked(tmp_path: Path) -> None:
    client, data, backups = box(tmp_path)
    slot = backups / RESTORE_SLOT
    foreign = archive_of(tmp_path, vps_config(), "vps.tar.gz").read_bytes()
    refused = client.put("/restore", content=foreign)
    assert refused.status_code == 422 and "of a vps box" in refused.json()["detail"]
    assert not slot.exists() and read_task_request(data, RESTORE) is None
    assert client.put("/restore", content=b"not a gzip").status_code == 422
    assert client.put("/restore", content=b"").status_code == 422
    assert not slot.exists() and not list(backups.glob("*.part"))
    good = archive_of(tmp_path, home_config(), "home.tar.gz").read_bytes()
    asked = client.put("/restore", content=good)
    assert asked.status_code == 200 and asked.json()["restore"]["pending"] is True
    assert slot.read_bytes() == good and slot.stat().st_mode & 0o777 == 0o600


def test_an_upload_past_the_limit_is_refused_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, data, backups = box(tmp_path)
    monkeypatch.setattr(backups_module, "MAX_RESTORE_BYTES", 10)
    answer = client.put("/restore", content=b"x" * 11)
    assert answer.status_code == 413
    assert not (backups / RESTORE_SLOT).exists() and not list(backups.glob("*.part"))
    assert read_task_request(data, RESTORE) is None


def test_a_core_without_its_places_keeps_no_archives(tmp_path: Path) -> None:
    client = TestClient(create_app(Config.model_validate(home_config())))
    assert client.get("/backups").status_code == 404
