"""The torrent client Transmission: its settings.json and its RPC.

What the sources say: docs/knowledge/transmission/rpc.md.

The image is linuxserver/transmission. The host (`vibedpn up`) renders the few keys of
``settings.json`` that the image has no variable for — above all ``rpc-bind-address``, which keeps
the RPC on 127.0.0.1 — and core talks to the RPC with the password from ``secrets/``. The RPC is
JSON-RPC 2.0 with ``snake_case`` names, as the current specification of Transmission 4.1 has it.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from vibedpn.config import Config

# The user the client runs as (PUID/PGID in compose.yaml): how the router recognises its traffic.
# Keep equal to the `PUID` there.
TRANSMISSION_UID = 7756
RPC_HOST = "127.0.0.1"
RPC_PORT = 9091
RPC_PATH = "/transmission/rpc"
RPC_USER = "vibedpn"
# The password of the RPC: generated at `torrents enable`, handed to the image as FILE__PASS
RPC_PASS_FILE = "transmission-rpc-pass"
RPC_TIMEOUT_SECONDS = 10.0
SESSION_HEADER = "X-Transmission-Session-Id"
# Where the host directories appear in the container: /config is data/transmission/config, and
# /downloads is torrents.download_dir. The image creates neither `complete` nor `incomplete`.
CONFIG_DIR = "data/transmission/config"
SETTINGS_FILE = "settings.json"
CONTAINER_DOWNLOADS = "/downloads"
COMPLETE_DIR = "complete"
INCOMPLETE_DIR = "incomplete"
CONTAINER_COMPLETE = f"{CONTAINER_DOWNLOADS}/{COMPLETE_DIR}"
CONTAINER_INCOMPLETE = f"{CONTAINER_DOWNLOADS}/{INCOMPLETE_DIR}"
HASH_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")
MAGNET_PREFIX = "magnet:?"
MAX_TORRENT_BYTES = 8 * 1024 * 1024  # a .torrent file is kilobytes; the RPC takes it as one body
# Transmission's own numbers (rpc-spec.md): a status, and the priority of a file
STATUSES = {
    0: "stopped",
    1: "check_wait",
    2: "checking",
    3: "download_wait",
    4: "downloading",
    5: "seed_wait",
    6: "seeding",
}
PRIORITIES = {-1: "low", 0: "normal", 1: "high"}
PRIORITY_FIELDS = {"low": "priority_low", "normal": "priority_normal", "high": "priority_high"}
SUMMARY_FIELDS = (
    "hash_string",
    "name",
    "status",
    "percent_done",
    "rate_download",
    "rate_upload",
    "eta",
    "total_size",
    "upload_ratio",
    "error",
    "error_string",
)
DETAIL_FIELDS = (*SUMMARY_FIELDS, "download_dir", "files", "file_stats", "peers", "tracker_stats")
SESSION_FIELDS = (
    "speed_limit_down",
    "speed_limit_down_enabled",
    "speed_limit_up",
    "speed_limit_up_enabled",
)


class TransmissionError(RuntimeError):
    """The client could not do what was asked; the message is meant for the operator."""


class TransmissionUnavailableError(TransmissionError):
    """The client is not running, does not answer, or refuses the password."""


class TorrentNotFoundError(TransmissionError):
    """No torrent with this hash."""


class TorrentInputError(TransmissionError):
    """The request names something Transmission cannot take."""


LIMIT_KEYS = frozenset(
    {"speed-limit-down", "speed-limit-down-enabled", "speed-limit-up", "speed-limit-up-enabled"}
)


def settings_keys(config: Config) -> dict[str, object]:
    """The keys of ``settings.json`` that follow config.yaml. Everything else in the file is the
    client's own and stays as it is; the password and the whitelist come from the image's
    environment (compose.yaml)."""
    torrents = config.torrents
    keys: dict[str, object] = {
        "rpc-bind-address": RPC_HOST,
        "rpc-port": RPC_PORT,
        "download-dir": CONTAINER_COMPLETE,
        "incomplete-dir": CONTAINER_INCOMPLETE,
        "incomplete-dir-enabled": True,
        "peer-port": torrents.peer_port,
        "peer-port-random-on-start": False,
        # no UPnP or NAT-PMP: the router of the provider is not ours to open
        "port-forwarding-enabled": False,
        "speed-limit-down-enabled": torrents.speed_limit_down is not None,
        "speed-limit-up-enabled": torrents.speed_limit_up is not None,
    }
    # a limit that is off keeps whatever number the client remembers: the panel switches it off
    # and on again, and the number is not ours to reset
    if torrents.speed_limit_down is not None:
        keys["speed-limit-down"] = torrents.speed_limit_down
    if torrents.speed_limit_up is not None:
        keys["speed-limit-up"] = torrents.speed_limit_up
    return keys


def limit_params(config: Config) -> dict[str, object]:
    """The speed limits of config.yaml as ``session_set`` takes them (kB/s)."""
    torrents = config.torrents
    params: dict[str, object] = {
        "speed_limit_down_enabled": torrents.speed_limit_down is not None,
        "speed_limit_up_enabled": torrents.speed_limit_up is not None,
    }
    if torrents.speed_limit_down is not None:
        params["speed_limit_down"] = torrents.speed_limit_down
    if torrents.speed_limit_up is not None:
        params["speed_limit_up"] = torrents.speed_limit_up
    return params


def settings_differ(existing: str | None, config: Config, *, limits: bool = True) -> bool:
    """Whether the file on disk lacks one of our keys or holds another value for it; ``limits``
    false leaves the speed limits out, which a running client holds ahead of its file. A file that
    is not JSON counts as different: the client would not start from it either."""
    if existing is None:
        return True
    try:
        data = json.loads(existing)
    except ValueError:
        return True
    if not isinstance(data, dict):
        return True
    return any(
        data.get(key) != value
        for key, value in settings_keys(config).items()
        if limits or key not in LIMIT_KEYS
    )


def settings_text(existing: str | None, config: Config) -> str:
    """The file with our keys set. An unreadable one is replaced: the image fills the rest of the
    defaults in at its start."""
    data: dict[str, Any] = {}
    if existing is not None:
        try:
            loaded = json.loads(existing)
            data = loaded if isinstance(loaded, dict) else {}
        except ValueError:
            data = {}
    data.update(settings_keys(config))
    return json.dumps(data, indent=4, sort_keys=True) + "\n"


def read_rpc_password(secrets_dir: Path) -> str:
    try:
        password = (secrets_dir / RPC_PASS_FILE).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise TransmissionUnavailableError(
            f"cannot read {RPC_PASS_FILE}: {exc.strerror or exc}; run `vibedpn torrents enable`"
        ) from exc
    if not password:
        raise TransmissionUnavailableError(
            f"{RPC_PASS_FILE} is empty; run `vibedpn torrents enable`"
        )
    return password


def check_hash(value: str) -> str:
    """A torrent hash as the API takes it, lower case."""
    if not HASH_PATTERN.fullmatch(value):
        raise TorrentInputError(f"{value!r} is not a torrent hash (40 hexadecimal characters)")
    return value.lower()


def check_subdir(value: str | None) -> str | None:
    """A folder inside the downloads: names separated by '/', none of them '.', '..' or empty."""
    if value is None or value == "":
        return None
    parts = value.split("/")
    if any(part in ("", ".", "..") or "\\" in part or "\x00" in part for part in parts):
        raise TorrentInputError(f"{value!r} is not a folder inside the downloads")
    return value


def check_metainfo(value: str) -> str:
    """The base64 of a .torrent file: decodable, not huge, and bencoded (a dictionary)."""
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise TorrentInputError("torrent: not base64") from exc
    if not raw.startswith(b"d") or len(raw) > MAX_TORRENT_BYTES:
        raise TorrentInputError("torrent: not a .torrent file")
    return value


@dataclass(frozen=True)
class RpcClient:
    """Calls to the RPC of the running client; one HTTP request per call (a 409 is repeated once
    with the session id the client names)."""

    password: str
    url: str = f"http://{RPC_HOST}:{RPC_PORT}{RPC_PATH}"
    transport: httpx.BaseTransport | None = None

    def call(self, method: str, params: Mapping[str, object] | None = None) -> dict[str, Any]:
        body = {"jsonrpc": "2.0", "method": method, "params": dict(params or {}), "id": 1}
        session_id = ""
        try:
            with httpx.Client(
                timeout=RPC_TIMEOUT_SECONDS, transport=self.transport, trust_env=False
            ) as client:
                for _attempt in range(2):
                    response = client.post(
                        self.url,
                        json=body,
                        auth=(RPC_USER, self.password),
                        headers={SESSION_HEADER: session_id},
                    )
                    if response.status_code != httpx.codes.CONFLICT:
                        break
                    session_id = response.headers.get(SESSION_HEADER, "")
        except httpx.HTTPError as exc:
            raise TransmissionUnavailableError(
                f"Transmission does not answer at {self.url}: {exc.__class__.__name__}"
            ) from exc
        return self._result(method, response)

    @staticmethod
    def _result(method: str, response: httpx.Response) -> dict[str, Any]:
        if response.status_code == httpx.codes.UNAUTHORIZED:
            raise TransmissionUnavailableError(
                f"Transmission refused the password in {RPC_PASS_FILE}: `vibedpn up` recreates it"
            )
        if response.status_code != httpx.codes.OK:
            raise TransmissionUnavailableError(
                f"Transmission answered {method} with HTTP {response.status_code}"
            )
        try:
            answer = response.json()
        except ValueError as exc:
            raise TransmissionError(f"Transmission answered {method} with no JSON") from exc
        if not isinstance(answer, dict):
            raise TransmissionError(f"Transmission answered {method} with no JSON object")
        error = answer.get("error")
        if error is not None:
            data = error.get("data") if isinstance(error, dict) else None
            detail = data.get("error_string") if isinstance(data, dict) else None
            message = error.get("message") if isinstance(error, dict) else None
            raise TransmissionError(f"Transmission refused {method}: {detail or message or error}")
        result = answer.get("result")
        return result if isinstance(result, dict) else {}

    # --- what the API needs ----------------------------------------------------------------

    def torrents(
        self, fields: tuple[str, ...], hashes: list[str] | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, object] = {"fields": list(fields)}
        if hashes is not None:
            params["ids"] = hashes
        found = self.call("torrent_get", params).get("torrents", [])
        return [item for item in found if isinstance(item, dict)] if isinstance(found, list) else []

    def torrent(self, torrent_hash: str, fields: tuple[str, ...]) -> dict[str, Any]:
        found = self.torrents(fields, [check_hash(torrent_hash)])
        if not found:
            raise TorrentNotFoundError(f"no torrent {torrent_hash}")
        return found[0]

    def add(
        self, *, magnet: str | None, metainfo: str | None, subdir: str | None, paused: bool
    ) -> tuple[dict[str, Any], bool]:
        """``(torrent_added or torrent_duplicate, whether it was a duplicate)``."""
        if (magnet is None) == (metainfo is None):
            raise TorrentInputError("give exactly one of magnet and torrent")
        params: dict[str, object] = {"paused": paused}
        if magnet is not None:
            if not magnet.startswith(MAGNET_PREFIX):
                raise TorrentInputError("magnet: not a magnet link")
            params["filename"] = magnet
        elif metainfo is not None:
            params["metainfo"] = check_metainfo(metainfo)
        folder = check_subdir(subdir)
        if folder is not None:
            params["download_dir"] = f"{CONTAINER_COMPLETE}/{folder}"
        result = self.call("torrent_add", params)
        added = result.get("torrent_added")
        if isinstance(added, dict):
            return added, False
        duplicate = result.get("torrent_duplicate")
        if isinstance(duplicate, dict):
            return duplicate, True
        raise TransmissionError("Transmission added nothing and named no duplicate")

    def act(
        self, method: str, torrent_hash: str, params: Mapping[str, object] | None = None
    ) -> None:
        """``torrent_start``, ``torrent_stop``, ``torrent_remove`` and ``torrent_set`` of one
        torrent; Transmission names no error for an unknown id, so it is looked up first."""
        known = check_hash(torrent_hash)
        self.torrent(known, ("hash_string",))
        self.call(method, {"ids": [known], **(params or {})})

    def session(self) -> dict[str, Any]:
        return self.call("session_get", {"fields": list(SESSION_FIELDS)})

    def free_space(self, path: str) -> tuple[int, int] | None:
        """``(free, total)`` bytes of ``path`` in the container; ``None`` when it is not there."""
        try:
            result = self.call("free_space", {"path": path})
        except TransmissionUnavailableError:
            raise
        except TransmissionError:
            return None
        free, total = result.get("size_bytes"), result.get("total_size")
        if isinstance(free, int) and isinstance(total, int) and free >= 0 and total >= 0:
            return free, total
        return None
