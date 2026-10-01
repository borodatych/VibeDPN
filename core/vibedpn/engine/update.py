"""An update of the box asked for in the panel (decision 26, extended 2026-09-25)

core cannot update the host: the checkout, the CLI and the images are the host's
So, as with a change the panel makes, core leaves a request file
A systemd path unit notices it and runs one fixed command
Here that command is `vibedpn update --requested`: core passes no argument, only the moment it asked
The host writes the result back where core reads it, with the revision before and after
Every `up` writes the revision the box runs, so the panel can show it before anyone asks
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from vibedpn.atomic import write_private
from vibedpn.engine.apply import ApplyError, HostTask, request_time, write_request

REVISION_FILE = "revision.json"
# Its result carries the revisions before and after, so it keeps its own result functions below
UPDATE = HostTask(
    request="update-request",
    result="update-result.json",
    unit="vibedpn-update-request",
    path_description="VibeDPN: an update asked in the panel",
    service_description="VibeDPN: vibedpn update asked in the panel",
    command="update --requested",
    # install.sh, a pull of every image and a restart of the box: minutes on a slow line
    timeout=30 * 60.0,
    no_answer="the host did not run the update: journalctl -u vibedpn-update-request,"
    " or sudo vibedpn update",
)


@dataclass(frozen=True)
class Revision:
    """The commit of the checkout the box runs"""

    branch: str
    commit: str  # short hash
    committed_at: str  # ISO 8601, as git prints it


@dataclass(frozen=True)
class UpdateResult:
    requested_at: float
    finished_at: float
    ok: bool
    message: str
    before: str  # the short commit before, "" when unknown
    after: str


@dataclass(frozen=True)
class UpdateState:
    pending: bool  # a request newer than the last result
    last: UpdateResult | None


def request_update(data_dir: Path, now: float) -> None:
    write_request(data_dir / UPDATE.request, now, "update asked in the panel")


def read_update_request(data_dir: Path) -> float | None:
    return request_time(data_dir / UPDATE.request)


def write_update_result(data_dir: Path, result: UpdateResult) -> None:
    _write(data_dir / UPDATE.result, asdict(result))


def read_update_result(data_dir: Path) -> UpdateResult | None:
    raw = _read(data_dir / UPDATE.result)
    try:
        return UpdateResult(
            requested_at=float(raw["requested_at"]),
            finished_at=float(raw["finished_at"]),
            ok=bool(raw["ok"]),
            message=str(raw["message"]),
            before=str(raw["before"]),
            after=str(raw["after"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def update_state(data_dir: Path, now: float) -> UpdateState:
    requested = read_update_request(data_dir)
    last = read_update_result(data_dir)
    waiting = requested is not None and (last is None or last.requested_at < requested)
    if requested is not None and waiting and now - requested > UPDATE.timeout:
        timed_out = UpdateResult(requested, now, False, UPDATE.no_answer, "", "")
        return UpdateState(pending=False, last=timed_out)
    return UpdateState(pending=waiting, last=last)


def write_revision(data_dir: Path, revision: Revision) -> None:
    _write(data_dir / REVISION_FILE, asdict(revision))


def read_revision(data_dir: Path) -> Revision | None:
    raw = _read(data_dir / REVISION_FILE)
    try:
        return Revision(str(raw["branch"]), str(raw["commit"]), str(raw["committed_at"]))
    except (KeyError, TypeError):
        return None


def _write(path: Path, data: dict[str, Any]) -> None:
    try:
        write_private(path, json.dumps(data) + "\n")
    except OSError as exc:
        raise ApplyError(f"cannot write {path}: {exc.strerror or exc}") from exc


def _read(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}
