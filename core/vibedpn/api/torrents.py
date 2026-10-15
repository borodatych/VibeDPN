"""``/torrents``: the torrent client Transmission as the panel uses it.

The contract is docs/knowledge/transmission/rpc.md, section "API ядра". core is the only one that
talks to the RPC of the client; the panel never does.

Torrents are named by their hash, which survives a restart of the client, and not by the number
Transmission hands out. A client that is off or does not answer is ``503`` with a phrase for the
operator, an unknown torrent is ``404``, a request the client cannot take is ``422``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, TypeVar

import httpx
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from vibedpn.api.models import ApplyView
from vibedpn.api.state import BoxState
from vibedpn.api.tasks import ask_host, task_view
from vibedpn.config import (
    DEFAULT_TORRENTS_DIR,
    TORRENTS_USB_DIR,
    TORRENTS_USB_MOUNTPOINT,
    Config,
)
from vibedpn.config_edit import ConfigEditError, set_torrents_limits, set_torrents_storage
from vibedpn.engine.apply import APPLY, STORAGE_SCAN
from vibedpn.engine.storage import DEVICES_FILE
from vibedpn.engine.transmission import (
    CONTAINER_COMPLETE,
    CONTAINER_DOWNLOADS,
    DETAIL_FIELDS,
    PRIORITIES,
    PRIORITY_FIELDS,
    STATUSES,
    SUMMARY_FIELDS,
    RpcClient,
    TorrentInputError,
    TorrentNotFoundError,
    TransmissionError,
    TransmissionUnavailableError,
    read_rpc_password,
)

T = TypeVar("T")
OFF = "the torrent client is off: `vibedpn torrents enable`, then `vibedpn up`"
NOT_STARTED = "the torrent client has not started yet: `vibedpn up` starts it"
Priority = Literal["low", "normal", "high"]


class TorrentSummary(BaseModel):
    id: str  # the hash
    name: str
    status: str  # a key of STATUSES
    progress: float
    rate_down: int
    rate_up: int
    eta: int | None
    size: int
    ratio: float | None
    error: str | None


class TorrentList(BaseModel):
    torrents: list[TorrentSummary]
    rate_down: int
    rate_up: int


class TorrentAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    magnet: str | None = None
    torrent: str | None = None  # base64 of a .torrent
    subdir: str | None = None
    paused: bool = False

    @model_validator(mode="after")
    def exactly_one_source(self) -> TorrentAdd:
        if (self.magnet is None) == (self.torrent is None):
            raise ValueError("give exactly one of magnet and torrent")
        return self


class TorrentAdded(BaseModel):
    id: str
    name: str
    duplicate: bool


class TorrentFile(BaseModel):
    index: int
    name: str
    size: int
    done: int
    wanted: bool
    priority: Priority


class TorrentPeer(BaseModel):
    address: str
    client: str
    progress: float
    rate_down: int
    rate_up: int
    flags: str


class TorrentTracker(BaseModel):
    announce: str
    host: str
    seeders: int | None
    leechers: int | None
    last_announce_ok: bool
    last_announce_result: str
    last_announce_time: int


class TorrentDetail(TorrentSummary):
    download_dir: str
    files: list[TorrentFile]
    peers: list[TorrentPeer]
    trackers: list[TorrentTracker]


class FilesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indices: list[int] = Field(min_length=1)
    wanted: bool | None = None
    priority: Priority | None = None

    @model_validator(mode="after")
    def says_something(self) -> FilesUpdate:
        if self.wanted is None and self.priority is None:
            raise ValueError("give wanted, priority or both")
        if any(index < 0 for index in self.indices):
            raise ValueError("indices: a file index is not negative")
        return self


class SessionView(BaseModel):
    speed_limit_down: int
    speed_limit_down_enabled: bool
    speed_limit_up: int
    speed_limit_up_enabled: bool
    rate_down: int
    rate_up: int


class SessionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speed_limit_down: int | None = Field(default=None, ge=1)
    speed_limit_down_enabled: bool | None = None
    speed_limit_up: int | None = Field(default=None, ge=1)
    speed_limit_up_enabled: bool | None = None


class StorageDisk(BaseModel):
    configured: bool
    uuid: str | None
    mounted: bool


class StorageDevice(BaseModel):
    uuid: str
    label: str | None
    fstype: str
    size: int
    device: str
    mountpoint: str | None
    supported: bool
    current: bool


class StorageView(BaseModel):
    download_dir: str
    free_bytes: int | None
    total_bytes: int | None
    egress: str
    storage: StorageDisk
    devices: list[StorageDevice]
    scanned_at: float | None
    state: ApplyView


class StorageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uuid: str | None


def summary_of(raw: dict[str, Any]) -> TorrentSummary:
    eta, ratio = raw.get("eta", -1), raw.get("upload_ratio", -1)
    error = raw.get("error_string") if raw.get("error", 0) else None
    return TorrentSummary(
        id=str(raw.get("hash_string", "")),
        name=str(raw.get("name", "")),
        status=STATUSES.get(raw.get("status", -1), "stopped"),
        progress=float(raw.get("percent_done", 0.0)),
        rate_down=int(raw.get("rate_download", 0)),
        rate_up=int(raw.get("rate_upload", 0)),
        eta=eta if isinstance(eta, int) and eta >= 0 else None,
        size=int(raw.get("total_size", 0)),
        ratio=ratio if isinstance(ratio, int | float) and ratio >= 0 else None,
        error=str(error) if error else None,
    )


def _files_of(raw: dict[str, Any]) -> list[TorrentFile]:
    files, stats = raw.get("files", []), raw.get("file_stats", [])
    found = []
    for index, (item, stat) in enumerate(zip(files, stats, strict=False)):
        found.append(
            TorrentFile(
                index=index,
                name=str(item.get("name", "")),
                size=int(item.get("length", 0)),
                done=int(stat.get("bytes_completed", 0)),
                wanted=bool(stat.get("wanted", True)),
                priority=PRIORITIES.get(stat.get("priority", 0), "normal"),  # type: ignore[arg-type]
            )
        )
    return found


def _count(value: object) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None


def detail_of(raw: dict[str, Any], download_dir: str) -> TorrentDetail:
    where = str(raw.get("download_dir", CONTAINER_COMPLETE))
    return TorrentDetail(
        **summary_of(raw).model_dump(),
        download_dir=where.replace(CONTAINER_DOWNLOADS, download_dir, 1),
        files=_files_of(raw),
        peers=[
            TorrentPeer(
                address=str(peer.get("address", "")),
                client=str(peer.get("client_name", "")),
                progress=float(peer.get("progress", 0.0)),
                rate_down=int(peer.get("rate_to_client", 0)),
                rate_up=int(peer.get("rate_to_peer", 0)),
                flags=str(peer.get("flag_str", "")),
            )
            for peer in raw.get("peers", [])
        ],
        trackers=[
            TorrentTracker(
                announce=str(item.get("announce", "")),
                host=str(item.get("host", "")),
                seeders=_count(item.get("seeder_count")),
                leechers=_count(item.get("leecher_count")),
                last_announce_ok=bool(item.get("last_announce_succeeded", False)),
                last_announce_result=str(item.get("last_announce_result", "")),
                last_announce_time=int(item.get("last_announce_time", 0)),
            )
            for item in raw.get("tracker_stats", [])
        ],
    )


def _session_view(session: dict[str, Any], rate_down: int, rate_up: int) -> SessionView:
    return SessionView(
        speed_limit_down=int(session.get("speed_limit_down", 0)),
        speed_limit_down_enabled=bool(session.get("speed_limit_down_enabled", False)),
        speed_limit_up=int(session.get("speed_limit_up", 0)),
        speed_limit_up_enabled=bool(session.get("speed_limit_up_enabled", False)),
        rate_down=rate_down,
        rate_up=rate_up,
    )


def read_devices(data_dir: Path | None) -> tuple[list[StorageDevice], float | None]:
    """The disks the host saw at its last look (engine/storage.py), without the ``current`` mark."""
    if data_dir is None:
        return [], None
    try:
        raw = json.loads((data_dir / DEVICES_FILE).read_text(encoding="utf-8"))
        devices = [StorageDevice(**item, current=False) for item in raw.get("devices", [])]
        return devices, float(raw["scanned_at"])
    except (OSError, ValueError, KeyError, TypeError, ValidationError):
        return [], None


def _merged_state(data_dir: Path) -> ApplyView:
    """The newest of the last apply and the last look at the disks: the panel waits for either."""
    apply, scan = task_view(data_dir, APPLY), task_view(data_dir, STORAGE_SCAN)
    newest = max((apply, scan), key=lambda item: item.finished_at or 0.0)
    return ApplyView(
        pending=apply.pending or scan.pending,
        ok=newest.ok,
        message=newest.message,
        finished_at=newest.finished_at,
    )


def add_torrents_routes(  # noqa: PLR0915 - one function per route, as the other route groups
    application: FastAPI,
    current: Callable[[], Config | None],
    state: BoxState | None,
    secrets_dir: Path | None,
    data_dir: Path | None,
    transport: httpx.BaseTransport | None = None,
) -> None:
    def box() -> Config:
        config = current()
        if config is None or config.network is None or not config.torrents.enabled:
            raise HTTPException(status_code=503, detail=OFF)
        return config

    def client() -> RpcClient:
        box()
        if secrets_dir is None:
            raise HTTPException(status_code=503, detail=NOT_STARTED)
        try:
            return RpcClient(read_rpc_password(secrets_dir), transport=transport)
        except TransmissionUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    def guarded(call: Callable[[RpcClient], T]) -> T:
        try:
            return call(client())
        except TransmissionUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except TorrentNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except TorrentInputError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except TransmissionError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @application.get("/torrents", response_model=TorrentList)
    def list_torrents() -> TorrentList:
        found = [summary_of(item) for item in guarded(lambda rpc: rpc.torrents(SUMMARY_FIELDS))]
        return TorrentList(
            torrents=found,
            rate_down=sum(item.rate_down for item in found),
            rate_up=sum(item.rate_up for item in found),
        )

    @application.post("/torrents", response_model=TorrentAdded, status_code=201)
    def add_torrent(request: TorrentAdd, response: Response) -> TorrentAdded:
        added, duplicate = guarded(
            lambda rpc: rpc.add(
                magnet=request.magnet,
                metainfo=request.torrent,
                subdir=request.subdir,
                paused=request.paused,
            )
        )
        if duplicate:
            response.status_code = 200
        return TorrentAdded(
            id=str(added.get("hash_string", "")),
            name=str(added.get("name", "")),
            duplicate=duplicate,
        )

    @application.post("/torrents/{torrent_id}/start", status_code=204)
    def start_torrent(torrent_id: str) -> Response:
        guarded(lambda rpc: rpc.act("torrent_start", torrent_id))
        return Response(status_code=204)

    @application.post("/torrents/{torrent_id}/stop", status_code=204)
    def stop_torrent(torrent_id: str) -> Response:
        guarded(lambda rpc: rpc.act("torrent_stop", torrent_id))
        return Response(status_code=204)

    @application.delete("/torrents/{torrent_id}", status_code=204)
    def remove_torrent(torrent_id: str, data: bool = False) -> Response:
        guarded(lambda rpc: rpc.act("torrent_remove", torrent_id, {"delete_local_data": data}))
        return Response(status_code=204)

    @application.get("/torrents/session", response_model=SessionView)
    def get_session() -> SessionView:
        return read_session()

    def read_session() -> SessionView:
        def read(rpc: RpcClient) -> SessionView:
            totals = rpc.torrents(("rate_download", "rate_upload"))
            return _session_view(
                rpc.session(),
                sum(int(item.get("rate_download", 0)) for item in totals),
                sum(int(item.get("rate_upload", 0)) for item in totals),
            )

        return guarded(read)

    @application.put("/torrents/session", response_model=SessionView)
    def put_session(request: SessionUpdate) -> SessionView:
        config = box()
        current_session = read_session()
        down = _limit(
            request.speed_limit_down, request.speed_limit_down_enabled, current_session, "down"
        )
        up = _limit(request.speed_limit_up, request.speed_limit_up_enabled, current_session, "up")
        params = request.model_dump(exclude_none=True)
        if params:
            guarded(lambda rpc: rpc.call("session_set", params))
        # config.yaml keeps the limits the host renders into settings.json: without this the next
        # `vibedpn up` would put the old ones back
        if state is not None and (
            (down, up) != (config.torrents.speed_limit_down, config.torrents.speed_limit_up)
        ):
            try:
                state.edit(
                    lambda path: set_torrents_limits(
                        path, down=down, up=up, change_down=True, change_up=True
                    ),
                    route=False,
                )
            except ConfigEditError as exc:
                raise HTTPException(
                    status_code=503,
                    detail=f"the limits are set, but config.yaml keeps the old: {exc}",
                ) from exc
        return read_session()

    @application.get("/torrents/storage", response_model=StorageView)
    def get_storage(refresh: bool = False) -> StorageView:
        config = box()
        if refresh and data_dir is not None:
            ask_host(data_dir, STORAGE_SCAN, "storage")
        return storage_view(config)

    def storage_view(config: Config) -> StorageView:
        devices, scanned_at = read_devices(data_dir)
        wanted = config.torrents.storage.uuid
        marked = [
            item.model_copy(
                update={"current": wanted is not None and item.uuid.lower() == wanted.lower()}
            )
            for item in devices
        ]
        space: tuple[int, int] | None = None
        try:
            space = client().free_space(CONTAINER_COMPLETE)
        except (HTTPException, TransmissionError):
            space = None  # the client is not up: the rest of the page still tells what it can
        return StorageView(
            download_dir=config.torrents.download_dir,
            free_bytes=None if space is None else space[0],
            total_bytes=None if space is None else space[1],
            egress=config.torrents.egress,
            storage=StorageDisk(
                configured=wanted is not None,
                uuid=wanted,
                mounted=any(
                    item.current and item.mountpoint == TORRENTS_USB_MOUNTPOINT for item in marked
                ),
            ),
            devices=marked,
            scanned_at=scanned_at,
            state=_merged_state(data_dir) if data_dir is not None else _idle(),
        )

    @application.put("/torrents/storage", response_model=StorageView, status_code=202)
    def put_storage(request: StorageUpdate) -> StorageView:
        config = box()
        if state is None or data_dir is None:
            raise HTTPException(status_code=503, detail="this core cannot change config.yaml")
        if (request.uuid or "").lower() != (config.torrents.storage.uuid or "").lower():
            uuid, fstype, where = _target(request.uuid, data_dir)
            try:
                state.edit(
                    lambda path: set_torrents_storage(
                        path, uuid=uuid, fstype=fstype, download_dir=where
                    ),
                    route=False,
                )
            except ConfigEditError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            ask_host(data_dir, APPLY, "download disk changed")
        return storage_view(box())

    @application.get("/torrents/{torrent_id}", response_model=TorrentDetail)
    def get_torrent(torrent_id: str) -> TorrentDetail:
        config = box()
        raw = guarded(lambda rpc: rpc.torrent(torrent_id, DETAIL_FIELDS))
        return detail_of(raw, config.torrents.download_dir)

    @application.put("/torrents/{torrent_id}/files", status_code=204)
    def put_files(torrent_id: str, request: FilesUpdate) -> Response:
        params: dict[str, object] = {}
        if request.wanted is not None:
            params["files_wanted" if request.wanted else "files_unwanted"] = request.indices
        if request.priority is not None:
            params[PRIORITY_FIELDS[request.priority]] = request.indices
        guarded(lambda rpc: rpc.act("torrent_set", torrent_id, params))
        return Response(status_code=204)


def _idle() -> ApplyView:
    return ApplyView(pending=False, ok=None, message="", finished_at=None)


def _limit(
    value: int | None, enabled: bool | None, session: SessionView, which: Literal["down", "up"]
) -> int | None:
    """The limit config.yaml should keep after this request: a number, or ``None`` for no limit."""
    held = session.speed_limit_down if which == "down" else session.speed_limit_up
    was_on = session.speed_limit_down_enabled if which == "down" else session.speed_limit_up_enabled
    on = was_on if enabled is None else enabled
    number = held if value is None else value
    if not on:
        return None
    if number < 1:
        raise HTTPException(
            status_code=422, detail=f"speed_limit_{which}: switching a limit on needs a number"
        )
    return number


def _target(uuid: str | None, data_dir: Path) -> tuple[str | None, str | None, str]:
    """``(uuid, fstype, download_dir)`` for the disk the owner picked, from what the host saw."""
    if uuid is None:
        return None, None, DEFAULT_TORRENTS_DIR
    devices, _scanned = read_devices(data_dir)
    device = next((item for item in devices if item.uuid.lower() == uuid.lower()), None)
    if device is None:
        raise HTTPException(
            status_code=422,
            detail=f"the host saw no disk with UUID {uuid}: GET /torrents/storage?refresh=true",
        )
    if not device.supported:
        raise HTTPException(
            status_code=422,
            detail=f"disk {uuid} cannot be used ({device.fstype}): ext4, exfat or ntfs",
        )
    return device.uuid, device.fstype, TORRENTS_USB_DIR
