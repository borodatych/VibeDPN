"""``/doctor``: the check of the box from the panel (decision 37)

Most checks of `vibedpn doctor` are the host's to make — Docker, ports, kernel modules, fail2ban —
so core asks the host and shows the report the host keeps in core's data directory: the one asked
here, or the daily one of the timer
"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from vibedpn.api.models import DoctorReportView, DoctorRequest, DoctorView
from vibedpn.api.tasks import ask_host, task_view
from vibedpn.doctor import MODE_LOCAL, MODE_NETWORK, REPORT_FILE
from vibedpn.engine.apply import DOCTOR, task_state

BUSY = "a check of the box is running: wait for its report"
NO_REPORTS = "this core keeps no report of the box"


def read_report(data_dir: Path) -> DoctorReportView | None:
    """The kept report; a missing or broken file is no report"""
    try:
        return DoctorReportView.model_validate_json((data_dir / REPORT_FILE).read_bytes())
    except (OSError, ValidationError):
        return None


def add_doctor_routes(application: FastAPI, data_dir: Path | None) -> None:
    def place() -> Path:
        if data_dir is None:
            raise HTTPException(status_code=404, detail=NO_REPORTS)
        return data_dir

    def view(data: Path) -> DoctorView:
        return DoctorView(report=read_report(data), state=task_view(data, DOCTOR))

    @application.get("/doctor", response_model=DoctorView)
    def get_doctor() -> DoctorView:
        return view(place())

    @application.post("/doctor", response_model=DoctorView)
    def ask_doctor(request: DoctorRequest) -> DoctorView:
        data = place()
        if task_state(data, DOCTOR, time.time()).pending:
            raise HTTPException(status_code=409, detail=BUSY)
        ask_host(data, DOCTOR, MODE_NETWORK if request.network else MODE_LOCAL)
        return view(data)
