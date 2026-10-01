"""Work the panel asks of the host: a change for `vibedpn up`, a backup, a restore (decision 26)

core has no access to Docker, on purpose: adding a WireGuard exit in the panel writes its file and
config.yaml, but only the host can generate the Compose service and start it. So core leaves a
request in its data directory, a systemd path unit on the host notices it and runs one fixed
command, which does the work and writes the result back where core reads it. core passes no
argument, only the moment it asked: a request cannot make the host do anything but that command.

The request is written plainly — open, write, close — and not by a rename: `PathChanged=` of
systemd.path(5) fires when a file opened for writing is closed. Pure except for the file I/O.
"""

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

from vibedpn.atomic import write_private

# compose.yaml mounts ./data/core of the box directory as core's data directory
BOX_DATA_DIR = Path("data/core")
# In the box directory itself, not in data/: a restore moves data/ aside while it holds the lock
HOST_LOCK_FILE = ".host-task.lock"


@dataclass(frozen=True)
class HostTask:
    """One kind of work core asks the host for"""

    request: str  # file in core's data directory, written by core
    result: str  # file next to it, written by the host
    unit: str  # the systemd path unit and its service
    path_description: str
    service_description: str
    command: str  # the arguments of `python -m vibedpn` the service runs
    # A request with no result after this means the host did not run the unit at all (no systemd, a
    # broken unit): said, not left "pending" forever
    timeout: float
    no_answer: str


APPLY = HostTask(
    request="apply-request",
    result="apply-result.json",
    unit="vibedpn-apply",
    path_description="VibeDPN: apply a change made in the panel",
    service_description="VibeDPN: vibedpn up for a change made in the panel",
    command="apply",
    timeout=300.0,  # `up` recreates a few containers in well under this
    no_answer="the host did not apply the change: journalctl -u vibedpn-apply, or sudo vibedpn up",
)
# The box stops for the copy: Postgres of the panel and the keystores of the nodes are consistent at
# rest only (decision 12), and stopping and starting every service takes a minute or two
BACKUP = HostTask(
    request="backup-request",
    result="backup-result.json",
    unit="vibedpn-backup-request",
    path_description="VibeDPN: a backup asked in the panel",
    service_description="VibeDPN: vibedpn backup asked in the panel",
    command="backup --requested",
    timeout=15 * 60.0,
    no_answer="the host did not make the backup: journalctl -u vibedpn-backup-request,"
    " or sudo vibedpn backup",
)
RESTORE = HostTask(
    request="restore-request",
    result="restore-result.json",
    unit="vibedpn-restore-request",
    path_description="VibeDPN: a restore asked in the panel",
    service_description="VibeDPN: vibedpn restore asked in the panel",
    command="restore --requested",
    timeout=15 * 60.0,
    no_answer="the host did not restore the backup: journalctl -u vibedpn-restore-request",
)
# The check of the box asked in the panel; the word of the request says whether it may leave the box
# (`vibedpn doctor --network`), and the report goes next to the result (doctor.REPORT_FILE)
DOCTOR = HostTask(
    request="doctor-request",
    result="doctor-result.json",
    unit="vibedpn-doctor-request",
    path_description="VibeDPN: a check of the box asked in the panel",
    service_description="VibeDPN: vibedpn doctor asked in the panel",
    command="doctor --requested",
    # the exit address of every uplink with --network: a few timeouts at most
    timeout=5 * 60.0,
    no_answer="the host did not check the box: journalctl -u vibedpn-doctor-request,"
    " or sudo vibedpn doctor",
)
# The last lines of a container's log asked in the panel; the request names the service and the
# number of lines, and the lines go next to the result (engine/logs.py)
LOGS = HostTask(
    request="logs-request",
    result="logs-result.json",
    unit="vibedpn-logs-request",
    path_description="VibeDPN: a container log asked in the panel",
    service_description="VibeDPN: vibedpn logs asked in the panel",
    command="logs --requested",
    # reading a log takes a second, but it waits for a backup or a restore holding the host lock
    timeout=BACKUP.timeout + 60.0,
    no_answer="the host did not read the log: journalctl -u vibedpn-logs-request,"
    " or sudo vibedpn logs",
)
# The tasks whose result is an ApplyResult; the update has its own (engine/update.py)
TASKS = (APPLY, BACKUP, RESTORE, DOCTOR, LOGS)
# The check the box makes of itself every day, without leaving it, so the panel shows a fresh report
DOCTOR_TIMER_UNIT = "vibedpn-doctor"
# A night hour off the weekly update (Sunday 04:00 and up to an hour), and a missed run is caught
# up after a power-off (systemd.timer(5), knowledge linux/boxBackup.md)
DOCTOR_TIMER = """[Unit]
Description=VibeDPN: the daily check of the box (vibedpn doctor --report)

[Timer]
OnCalendar=*-*-* 05:30:00
RandomizedDelaySec=30min
Persistent=true

[Install]
WantedBy=timers.target
"""


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


@contextmanager
def host_lock(box_dir: Path) -> Iterator[None]:
    """One task of the host at a time: each stops or starts the box

    The path unit and the owner running the same command by hand would otherwise both do the work
    The second waits, then finds the result written and has nothing left to do
    """
    descriptor = os.open(box_dir / HOST_LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)  # closing releases the lock


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


def read_task_reason(data_dir: Path, task: HostTask) -> str:
    """The second line of the request: why it was asked, or the word a task reads (``DOCTOR``)"""
    try:
        lines = (data_dir / task.request).read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    return lines[1].strip() if len(lines) > 1 else ""


def request_task(data_dir: Path, task: HostTask, now: float, reason: str) -> None:
    """Ask the host to run the command of ``task``"""
    write_request(data_dir / task.request, now, reason)


def read_task_request(data_dir: Path, task: HostTask) -> float | None:
    """The time of the last request, or ``None`` when there is none (or it is unreadable)"""
    return request_time(data_dir / task.request)


def write_task_result(data_dir: Path, task: HostTask, result: ApplyResult) -> None:
    path = data_dir / task.result
    try:
        write_private(path, json.dumps(asdict(result)) + "\n")
    except OSError as exc:
        raise ApplyError(f"cannot write {path}: {exc.strerror or exc}") from exc


def read_task_result(data_dir: Path, task: HostTask) -> ApplyResult | None:
    try:
        raw = json.loads((data_dir / task.result).read_text(encoding="utf-8"))
        return ApplyResult(
            requested_at=float(raw["requested_at"]),
            finished_at=float(raw["finished_at"]),
            ok=bool(raw["ok"]),
            message=str(raw["message"]),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def task_state(data_dir: Path, task: HostTask, now: float) -> ApplyState:
    requested = read_task_request(data_dir, task)
    last = read_task_result(data_dir, task)
    waiting = requested is not None and (last is None or last.requested_at < requested)
    if requested is not None and waiting and now - requested > task.timeout:
        return ApplyState(pending=False, last=ApplyResult(requested, now, False, task.no_answer))
    return ApplyState(pending=waiting, last=last)


def render_task_units(box_dir: Path, python: str, task: HostTask) -> dict[str, str]:
    """The path unit watching the request of ``task`` and the service running its command

    A oneshot service has no start timeout by default (systemd.service(5)): a backup or an update
    takes minutes
    """
    request = box_dir / BOX_DATA_DIR / task.request
    return {
        f"{task.unit}.path": (
            "[Unit]\n"
            f"Description={task.path_description}\n\n"
            "[Path]\n"
            f"PathChanged={request}\n\n"
            "[Install]\n"
            "WantedBy=multi-user.target\n"
        ),
        f"{task.unit}.service": (
            "[Unit]\n"
            f"Description={task.service_description}\n"
            "After=docker.service network-online.target\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            f"ExecStart={python} -m vibedpn {task.command} --dir {box_dir}\n"
        ),
    }


def render_doctor_timer(box_dir: Path, python: str) -> dict[str, str]:
    """The daily check: a timer and the service writing the report the panel shows"""
    return {
        f"{DOCTOR_TIMER_UNIT}.timer": DOCTOR_TIMER,
        f"{DOCTOR_TIMER_UNIT}.service": (
            "[Unit]\n"
            "Description=VibeDPN: the daily check of the box\n"
            "After=docker.service network-online.target\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            f"ExecStart={python} -m vibedpn doctor --report --dir {box_dir}\n"
        ),
    }
