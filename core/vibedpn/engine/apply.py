"""Changes made in the panel that need `vibedpn up` on the host (decision 26).

core has no access to Docker, on purpose: adding a WireGuard exit in the panel writes its file and
config.yaml, but only the host can generate the Compose service and start it. So core leaves a
request in its data directory, a systemd path unit on the host notices it and runs `vibedpn apply`,
which runs `up` and writes the result back where core reads it.

The request is written plainly — open, write, close — and not by a rename: `PathChanged=` of
systemd.path(5) fires when a file opened for writing is closed. Pure except for the file I/O.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from vibedpn.atomic import write_private

REQUEST_FILE = "apply-request"
RESULT_FILE = "apply-result.json"
APPLY_UNIT = "vibedpn-apply"
# compose.yaml mounts ./data/core of the box directory as core's data directory
BOX_DATA_DIR = Path("data/core")
# `up` recreates a few containers in well under this; a request with no result after it means the
# host did not run the unit at all (no systemd, a broken unit) — said, not left "applying" forever.
APPLY_TIMEOUT_SECONDS = 300.0
NO_ANSWER = "the host did not apply the change: journalctl -u vibedpn-apply, or sudo vibedpn up"


class ApplyError(RuntimeError):
    """A request or a result could not be written or read."""


@dataclass(frozen=True)
class ApplyResult:
    requested_at: float  # the request this run applied
    finished_at: float
    ok: bool
    message: str


@dataclass(frozen=True)
class ApplyState:
    pending: bool  # a request newer than the last result
    last: ApplyResult | None


def write_request(path: Path, now: float, reason: str) -> None:
    """A request to the host: its time, then why; opened and closed, so `PathChanged=` fires"""
    try:
        with path.open("w", encoding="utf-8") as handle:
            handle.write(f"{now}\n{reason}\n")
    except OSError as exc:
        raise ApplyError(f"cannot write {path}: {exc.strerror or exc}") from exc


def request_time(path: Path) -> float | None:
    """The time of the last request, or None when there is none (or it is unreadable)"""
    try:
        return float(path.read_text(encoding="utf-8").splitlines()[0])
    except (OSError, IndexError, ValueError):
        return None


def request_apply(data_dir: Path, now: float, reason: str) -> None:
    """Ask the host to run `vibedpn up`."""
    write_request(data_dir / REQUEST_FILE, now, reason)


def read_request(data_dir: Path) -> float | None:
    """The time of the last request, or ``None`` when there is none (or it is unreadable)."""
    return request_time(data_dir / REQUEST_FILE)


def write_result(data_dir: Path, result: ApplyResult) -> None:
    try:
        write_private(data_dir / RESULT_FILE, json.dumps(asdict(result)) + "\n")
    except OSError as exc:
        raise ApplyError(f"cannot write {data_dir / RESULT_FILE}: {exc.strerror or exc}") from exc


def read_result(data_dir: Path) -> ApplyResult | None:
    try:
        raw = json.loads((data_dir / RESULT_FILE).read_text(encoding="utf-8"))
        return ApplyResult(
            requested_at=float(raw["requested_at"]),
            finished_at=float(raw["finished_at"]),
            ok=bool(raw["ok"]),
            message=str(raw["message"]),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def apply_state(data_dir: Path, now: float) -> ApplyState:
    requested = read_request(data_dir)
    last = read_result(data_dir)
    waiting = requested is not None and (last is None or last.requested_at < requested)
    if requested is not None and waiting and now - requested > APPLY_TIMEOUT_SECONDS:
        return ApplyState(pending=False, last=ApplyResult(requested, now, False, NO_ANSWER))
    return ApplyState(pending=waiting, last=last)


def render_units(box_dir: Path, python: str) -> dict[str, str]:
    """The path unit watching the request and the service running `vibedpn apply` for it."""
    request = box_dir / BOX_DATA_DIR / REQUEST_FILE
    return {
        f"{APPLY_UNIT}.path": (
            "[Unit]\n"
            "Description=VibeDPN: apply a change made in the panel\n\n"
            "[Path]\n"
            f"PathChanged={request}\n\n"
            "[Install]\n"
            "WantedBy=multi-user.target\n"
        ),
        f"{APPLY_UNIT}.service": (
            "[Unit]\n"
            "Description=VibeDPN: vibedpn up for a change made in the panel\n"
            "After=docker.service network-online.target\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            f"ExecStart={python} -m vibedpn apply --dir {box_dir}\n"
        ),
    }
