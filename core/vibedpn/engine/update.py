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
from collections.abc import Callable
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


# CI tags every image it publishes with the commit it was built from (docker/metadata-action,
# type=sha: `sha-` and the first seven characters of the commit)
COMMIT_TAG_PREFIX = "sha-"
COMMIT_TAG_LENGTH = 7
# How far back an update looks for a commit whose images are all published: a burst of pushes
# while CI builds is far shorter; past it the box stays where it is and says why
SEARCH_DEPTH = 20


def commit_tag(commit: str) -> str:
    """The image tag CI gives the images of ``commit``"""
    return f"{COMMIT_TAG_PREFIX}{commit[:COMMIT_TAG_LENGTH]}"


def managed_tag(tag: str, branch_tag: str) -> bool:
    """Whether an update may pin ``tag`` to a commit: the tag of the branch, or a pin of its own
    A tag the owner set by hand in .env is theirs: an update pulls it as it is"""
    return tag == branch_tag or tag.startswith(COMMIT_TAG_PREFIX)


def retag(image: str, tag_from: str, tag_to: str) -> str:
    """``image`` with ``tag_from`` at the head of its tag replaced: `vibedpn-ui:next-full` keeps its
    suffix of the panel variant (compose.yaml appends it to the tag)"""
    name, _, tag = image.rpartition(":")
    if not name or not tag.startswith(tag_from):
        return image
    return f"{name}:{tag_to}{tag[len(tag_from) :]}"


@dataclass(frozen=True)
class UpdateTarget:
    commit: str | None  # the commit to move to; None: nothing newer than the box has its images
    building: str | None  # a newer commit whose images CI has not published yet


def pick_target(commits: list[str], current: str, ready: Callable[[str], bool]) -> UpdateTarget:
    """The newest commit of ``commits`` (newest first) whose images are all published

    The checkout and the images move together: the tag of the branch moves when CI has built,
    not when the commit lands, and an update between the two ran new code on old images
    The search stops at the commit the box runs: an update never moves the box back
    """
    building: str | None = None
    for commit in commits:
        if commit == current:
            return UpdateTarget(None, building)
        if ready(commit):
            return UpdateTarget(commit, building)
        building = building or commit
    return UpdateTarget(None, building)


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
    # a newer commit of the branch the update left alone: CI had not published its images yet
    building: str = ""


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
            building=str(raw.get("building", "")),  # a result written before the field: none
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
