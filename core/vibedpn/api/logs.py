"""``/logs``: the last lines of a container's log from the panel (decision 38)

Only the host sees Docker, so core asks the host and shows what it read (engine/logs.py)
The services offered are the ones `vibedpn up` told core about; the host checks the name again
"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from vibedpn.api.models import LogsReportView, LogsRequest, LogsView
from vibedpn.api.tasks import ask_host, task_view
from vibedpn.engine.apply import LOGS, task_state
from vibedpn.engine.logs import REPORT_FILE, SERVICES_FILE, parse_services, request_word

BUSY = "a log is being read: wait for it"
NO_LOGS = "this core reads no logs"


def read_services(data_dir: Path) -> list[str]:
    try:
        return parse_services((data_dir / SERVICES_FILE).read_text(encoding="utf-8"))
    except OSError:
        return []


def read_report(data_dir: Path) -> LogsReportView | None:
    """The kept log; a missing or broken file is none"""
    try:
        return LogsReportView.model_validate_json((data_dir / REPORT_FILE).read_bytes())
    except (OSError, ValidationError):
        return None


def add_logs_routes(application: FastAPI, data_dir: Path | None) -> None:
    def place() -> Path:
        if data_dir is None:
            raise HTTPException(status_code=404, detail=NO_LOGS)
        return data_dir

    def view(data: Path) -> LogsView:
        return LogsView(
            services=read_services(data), report=read_report(data), state=task_view(data, LOGS)
        )

    @application.get("/logs", response_model=LogsView)
    def get_logs() -> LogsView:
        return view(place())

    @application.post("/logs", response_model=LogsView)
    def ask_logs(request: LogsRequest) -> LogsView:
        data = place()
        if request.service not in read_services(data):
            raise HTTPException(
                status_code=422, detail=f"this box runs no service {request.service}"
            )
        if task_state(data, LOGS, time.time()).pending:
            raise HTTPException(status_code=409, detail=BUSY)
        ask_host(data, LOGS, request_word(request.service, request.tail))
        return view(data)
