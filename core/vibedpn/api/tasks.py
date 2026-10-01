"""Work core asks of the host, as the API shows it and asks for it (engine/apply.py, decision 26)"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import HTTPException

from vibedpn.api.models import ApplyView
from vibedpn.engine.apply import ApplyError, HostTask, request_task, task_state


def task_view(data_dir: Path, task: HostTask) -> ApplyView:
    """The last run of ``task`` on the host, and whether a request still waits for one"""
    progress = task_state(data_dir, task, time.time())
    last = progress.last
    return ApplyView(
        pending=progress.pending,
        ok=None if last is None else last.ok,
        message="" if last is None else last.message,
        finished_at=None if last is None else last.finished_at,
    )


def ask_host(data_dir: Path, task: HostTask, reason: str) -> None:
    """Leave the request the host's path unit picks up: core cannot start containers itself"""
    try:
        request_task(data_dir, task, time.time(), reason)
    except ApplyError as exc:
        raise HTTPException(
            status_code=503, detail=f"saved, but the host was not asked to act on it: {exc}"
        ) from exc
