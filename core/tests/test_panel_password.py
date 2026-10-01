"""The panel password changed from the panel

Core checks the current one, writes secrets/htpasswd in place and leaves the NodeUI hash for the
host, which moves it to the node
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import bcrypt
from fastapi.testclient import TestClient

from vibedpn.api.app import WRONG_PASSWORD, create_app
from vibedpn.bootstrap import (
    HTPASSWD_FILE,
    NODEUI_PASS_FILE,
    UI_USER,
    htpasswd_line,
    panel_password_matches,
)
from vibedpn.compose import adopt_node_password
from vibedpn.config import Config
from vibedpn.engine.apply import REQUEST_FILE

from .conftest import client_config, home_config, vps_config

OLD = "old-panel-pass"
NEW = "new-panel-pass"


def box(tmp_path: Path, raw: dict[str, Any]) -> tuple[TestClient, Path, Path]:
    secrets = tmp_path / "secrets"
    data = tmp_path / "data"
    secrets.mkdir(parents=True)
    data.mkdir(parents=True)
    (secrets / HTPASSWD_FILE).write_text(htpasswd_line(UI_USER, OLD), encoding="utf-8")
    app = create_app(Config.model_validate(raw), secrets_dir=secrets, data_dir=data)
    return TestClient(app), secrets / HTPASSWD_FILE, data


def matches(path: Path, password: str) -> bool:
    hashed = path.read_text(encoding="utf-8").strip().split(":", 1)[-1]
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("ascii"))


def test_the_new_password_needs_the_current_one(tmp_path: Path) -> None:
    client, htpasswd, data = box(tmp_path, home_config())
    before = htpasswd.read_text(encoding="utf-8")
    wrong = client.put("/panel/password", json={"current": "guess-1234", "new": NEW})
    assert wrong.status_code == 403 and wrong.json()["detail"] == WRONG_PASSWORD
    short = client.put("/panel/password", json={"current": OLD, "new": "short"})
    assert short.status_code == 422 and "at least 8 characters" in short.json()["detail"]
    assert htpasswd.read_text(encoding="utf-8") == before
    assert not (data / NODEUI_PASS_FILE).exists() and not (data / REQUEST_FILE).exists()


def test_the_panel_takes_it_at_once_adguard_and_the_node_after_the_host(tmp_path: Path) -> None:
    client, htpasswd, data = box(tmp_path, home_config())
    inode = htpasswd.stat().st_ino
    answer = client.put("/panel/password", json={"current": OLD, "new": NEW})
    assert answer.status_code == 200 and answer.json() == {"later": ["adguard", "nodeui"]}
    assert matches(htpasswd, NEW) and not matches(htpasswd, OLD)
    # in place: the panel mounts this one file and never sees one renamed over it
    assert htpasswd.stat().st_ino == inode and htpasswd.stat().st_mode & 0o777 == 0o600
    staged = data / NODEUI_PASS_FILE
    assert matches(staged, NEW) and staged.stat().st_mode & 0o777 == 0o600
    assert (data / REQUEST_FILE).exists()  # the host recreates AdGuard and the node
    assert panel_password_matches(htpasswd.parent, NEW)


def test_what_takes_it_later_depends_on_the_box(tmp_path: Path) -> None:
    client, _htpasswd, data = box(tmp_path / "client", client_config())
    answer = client.put("/panel/password", json={"current": OLD, "new": NEW})
    assert answer.json() == {"later": ["adguard"]}  # no node: nothing staged
    assert not (data / NODEUI_PASS_FILE).exists()
    vps, _htpasswd, data = box(tmp_path / "vps", vps_config())
    assert vps.put("/panel/password", json={"current": OLD, "new": NEW}).json() == {
        "later": ["nodeui"]
    }
    assert (data / NODEUI_PASS_FILE).exists()


def test_a_password_bcrypt_cannot_take_is_no_match(tmp_path: Path) -> None:
    (tmp_path / HTPASSWD_FILE).write_text(htpasswd_line(UI_USER, OLD), encoding="utf-8")
    assert panel_password_matches(tmp_path, OLD)
    assert not panel_password_matches(tmp_path, "x" * 100)  # longer than bcrypt takes
    (tmp_path / HTPASSWD_FILE).write_text("admin:not-a-hash\nother:x\n", encoding="utf-8")
    assert not panel_password_matches(tmp_path, OLD)


def test_the_host_moves_the_staged_hash_to_the_node(tmp_path: Path) -> None:
    staged_dir = tmp_path / "data" / "core"
    staged_dir.mkdir(parents=True)
    assert adopt_node_password(tmp_path, staged_dir) is None  # nothing waits
    (staged_dir / NODEUI_PASS_FILE).write_text("$2b$12$hash\n", encoding="utf-8")
    moved = adopt_node_password(tmp_path, staged_dir)
    assert moved == tmp_path / "data" / "myst-provider" / NODEUI_PASS_FILE
    assert moved.read_text(encoding="utf-8") == "$2b$12$hash\n"
    assert moved.stat().st_mode & 0o777 == 0o600
    assert not (staged_dir / NODEUI_PASS_FILE).exists()
