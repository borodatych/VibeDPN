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
from vibedpn.engine.apply import BOX_DATA_DIR, ApplyError, request_time, write_request

UPDATE_REQUEST_FILE = "update-request"
UPDATE_RESULT_FILE = "update-result.json"
REVISION_FILE = "revision.json"
UPDATE_REQUEST_UNIT = "vibedpn-update-request"
# install.sh, a pull of every image and a restart of the box: minutes on a slow line
# A request with no result after this means the host never ran the unit — said, not left "updating"
UPDATE_TIMEOUT_SECONDS = 30 * 60.0
NO_UPDATE_ANSWER = (
    "the host did not run the update: journalctl -u vibedpn-update-request, or sudo vibedpn update"
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
    write_request(data_dir / UPDATE_REQUEST_FILE, now, "update asked in the panel")


def read_update_request(data_dir: Path) -> float | None:
    return request_time(data_dir / UPDATE_REQUEST_FILE)


def write_update_result(data_dir: Path, result: UpdateResult) -> None:
    _write(data_dir / UPDATE_RESULT_FILE, asdict(result))


def read_update_result(data_dir: Path) -> UpdateResult | None:
    raw = _read(data_dir / UPDATE_RESULT_FILE)
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
    if requested is not None and waiting and now - requested > UPDATE_TIMEOUT_SECONDS:
        timed_out = UpdateResult(requested, now, False, NO_UPDATE_ANSWER, "", "")
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


def render_update_units(box_dir: Path, python: str) -> dict[str, str]:
    """The path unit watching the request and the service running the update for it

    A oneshot service has no start timeout by default (systemd.service(5)): an update takes minutes
    """
    request = box_dir / BOX_DATA_DIR / UPDATE_REQUEST_FILE
    return {
        f"{UPDATE_REQUEST_UNIT}.path": (
            "[Unit]\n"
            "Description=VibeDPN: an update asked in the panel\n\n"
            "[Path]\n"
            f"PathChanged={request}\n\n"
            "[Install]\n"
            "WantedBy=multi-user.target\n"
        ),
        f"{UPDATE_REQUEST_UNIT}.service": (
            "[Unit]\n"
            "Description=VibeDPN: vibedpn update asked in the panel\n"
            "After=docker.service network-online.target\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            f"ExecStart={python} -m vibedpn update --requested --dir {box_dir}\n"
        ),
    }


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
