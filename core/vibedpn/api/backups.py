"""``/backups`` and ``/restore``: the archives of the box from the panel (decision 36)

core lists, serves and deletes the archives of backups/ itself, and leaves a request for the host
for the rest: a backup stops every service, core among them, and a restore replaces its files
The archive to restore always lies in one place, backups/restore-upload.tar.gz, where an upload
or a listed archive goes: the host takes no name from core
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse

from vibedpn.api.models import ArchiveView, BackupsView
from vibedpn.api.tasks import ask_host, task_view
from vibedpn.config import Config
from vibedpn.engine.apply import BACKUP, RESTORE, task_state
from vibedpn.engine.backup import (
    ARCHIVE_MODE,
    ARCHIVE_NAME,
    RESTORE_SLOT,
    BackupError,
    archive_config,
    list_archives,
)

# The upload comes through the panel, and Bun refuses a request body past 128 MB by default
# (maxRequestBodySize in bun-types serve.d.ts): a bigger limit here would never be reached
# An archive of a box is tens of MB, so this leaves room for a long AdGuard journal
MAX_RESTORE_BYTES = 128 * 1024 * 1024
ARCHIVE_TYPE = "application/gzip"
BUSY = "the box is busy with a backup or a restore: wait for its result"
NO_BACKUPS = "this core keeps no archives of the box"


@dataclass(frozen=True)
class Place:
    """The box as it runs, core's data directory and the archives of the box"""

    box: Config
    data: Path
    backups: Path

    @property
    def slot(self) -> Path:
        return self.backups / RESTORE_SLOT

    def view(self) -> BackupsView:
        try:
            archives = list_archives(self.backups)
        except BackupError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return BackupsView(
            archives=[
                ArchiveView(name=item.name, size=item.size, created_at=item.created_at)
                for item in archives
            ],
            keep=self.box.backup.keep,
            backup=task_view(self.data, BACKUP),
            restore=task_view(self.data, RESTORE),
        )

    def idle(self) -> None:
        """One backup or restore at a time: each stops the box

        A request the host never answered stops waiting after its timeout and blocks nothing
        """
        for task in (BACKUP, RESTORE):
            if task_state(self.data, task, time.time()).pending:
                raise HTTPException(status_code=409, detail=BUSY)

    def archive(self, name: str) -> Path:
        """Only a name of an archive of the box: no path and no other file of backups/"""
        path = self.backups / name
        if not ARCHIVE_NAME.match(name) or not path.is_file():
            raise HTTPException(status_code=404, detail=f"no archive {name}")
        return path

    def check_slot(self) -> None:
        """The archive must be a box of this role this version can start

        The host checks it again, but a refusal here leaves nothing waiting and says why at once
        """
        try:
            restored = archive_config(self.slot)
        except BackupError as exc:
            self.slot.unlink(missing_ok=True)
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if restored.role is not self.box.role:
            self.slot.unlink(missing_ok=True)
            raise HTTPException(
                status_code=422,
                detail=f"the archive is of a {restored.role.value} box, this one is"
                f" {self.box.role.value}: restore it on a box of its role",
            )

    def take(self, name: str) -> None:
        """A listed archive into the slot, private from its first byte: it holds secrets"""
        source = self.archive(name)
        partial = self.slot.with_name(f"{RESTORE_SLOT}.part")
        try:
            descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, ARCHIVE_MODE)
            with os.fdopen(descriptor, "wb") as target, source.open("rb") as origin:
                shutil.copyfileobj(origin, target)
            partial.chmod(ARCHIVE_MODE)  # an older partial kept its mode through O_TRUNC
            partial.replace(self.slot)
        except OSError as exc:
            raise HTTPException(status_code=503, detail=f"cannot copy {name}: {exc}") from exc
        finally:
            partial.unlink(missing_ok=True)

    async def receive(self, request: Request) -> None:
        """The uploaded archive into the slot, refused past MAX_RESTORE_BYTES"""
        partial = self.slot.with_name(f"{RESTORE_SLOT}.part")
        size = 0
        try:
            self.backups.mkdir(parents=True, exist_ok=True)
            with partial.open("wb") as handle:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_RESTORE_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail=f"an archive of the box is at most {MAX_RESTORE_BYTES} bytes",
                        )
                    handle.write(chunk)
            if size == 0:
                raise HTTPException(status_code=422, detail="the upload is empty")
            partial.chmod(ARCHIVE_MODE)  # it holds the secrets of a box
            partial.replace(self.slot)
        except OSError as exc:
            raise HTTPException(status_code=503, detail=f"cannot keep the upload: {exc}") from exc
        finally:
            partial.unlink(missing_ok=True)


def add_backup_routes(
    application: FastAPI,
    current: Callable[[], Config | None],
    data_dir: Path | None,
    backups_dir: Path | None,
) -> None:
    def place() -> Place:
        box = current()
        if box is None or data_dir is None or backups_dir is None:
            raise HTTPException(status_code=404, detail=NO_BACKUPS)
        return Place(box, data_dir, backups_dir)

    @application.get("/backups", response_model=BackupsView)
    def get_backups() -> BackupsView:
        return place().view()

    @application.get("/backups/{name}")
    def download(name: str) -> FileResponse:
        return FileResponse(place().archive(name), media_type=ARCHIVE_TYPE, filename=name)

    @application.delete("/backups/{name}", status_code=204)
    def delete(name: str) -> Response:
        path = place().archive(name)
        try:
            path.unlink()
        except OSError as exc:
            raise HTTPException(status_code=503, detail=f"cannot remove {name}: {exc}") from exc
        return Response(status_code=204)

    @application.post("/backups", response_model=BackupsView)
    def make_backup() -> BackupsView:
        here = place()
        here.idle()
        ask_host(here.data, BACKUP, "backup asked in the panel")
        return here.view()

    @application.post("/backups/{name}/restore", response_model=BackupsView)
    def restore_listed(name: str) -> BackupsView:
        here = place()
        here.idle()
        here.take(name)
        here.check_slot()
        ask_host(here.data, RESTORE, f"restore of {name} asked in the panel")
        return here.view()

    @application.put("/restore", response_model=BackupsView)
    async def restore_upload(request: Request) -> BackupsView:
        here = place()
        here.idle()
        await here.receive(request)
        await asyncio.to_thread(here.check_slot)
        ask_host(here.data, RESTORE, "restore of an uploaded archive asked in the panel")
        return here.view()
