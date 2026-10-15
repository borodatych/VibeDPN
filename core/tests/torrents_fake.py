"""A stand-in for the RPC of Transmission 4.1.3, in the shapes a live daemon answered with
(15.10.2026): the session id handshake, Basic auth, JSON-RPC 2.0 with snake_case names."""

import base64
import json
from typing import Any

import httpx

HASH = "7ad0393e3790590660678ef4e876a5248dcdad8d"
OTHER_HASH = "0123456789abcdef0123456789abcdef01234567"
PASSWORD = "rpc-secret"
SESSION_ID = "fNGjWYAa8hhMMfukVc47W0F9tcTyVWFO4AJEMY3sIUrhxrO7"
GIB = 1024**3


def torrent(**changes: object) -> dict[str, Any]:
    """One entry of ``torrent_get`` for a torrent with a single 16 KiB file."""
    base: dict[str, Any] = {
        "download_dir": "/downloads/complete",
        "error": 0,
        "error_string": "",
        "eta": -2,
        "file_stats": [{"bytes_completed": 0, "priority": 0, "wanted": True}],
        "files": [
            {"begin_piece": 0, "bytes_completed": 0, "end_piece": 1, "length": 16384,
             "name": "probe.bin"}
        ],
        "hash_string": HASH,
        "id": 1,
        "name": "probe.bin",
        "peers": [],
        "percent_done": 0.0,
        "rate_download": 0,
        "rate_upload": 0,
        "status": 4,
        "total_size": 16384,
        "tracker_stats": [
            {"announce": "http://127.0.0.1:1/announce", "host": "127.0.0.1:1",
             "seeder_count": -1, "leecher_count": -1, "last_announce_succeeded": False,
             "last_announce_result": "", "last_announce_time": 0}
        ],
        "upload_ratio": 0.0,
    }  # fmt: skip
    return {**base, **changes}


class FakeTransmission:
    def __init__(self) -> None:
        self.torrents: list[dict[str, Any]] = [torrent()]
        self.session: dict[str, Any] = {
            "speed_limit_down": 100,
            "speed_limit_down_enabled": False,
            "speed_limit_up": 100,
            "speed_limit_up_enabled": False,
        }
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.session_checks = 0  # requests answered 409 for a missing or stale session id
        self.free = (100 * GIB, 500 * GIB)
        self.down = False
        self.expire_session = False

    # --- the HTTP layer ---------------------------------------------------------------------

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("refused", request=request)
        expected = "Basic " + base64.b64encode(f"vibedpn:{PASSWORD}".encode()).decode()
        if request.headers.get("authorization") != expected:
            return httpx.Response(401, text="Unauthorized")
        if request.headers.get("x-transmission-session-id") != SESSION_ID or self.expire_session:
            self.session_checks += 1
            self.expire_session = False
            return httpx.Response(409, headers={"X-Transmission-Session-Id": SESSION_ID})
        body = json.loads(request.content)
        return httpx.Response(200, json=self.dispatch(body))

    # --- the methods ------------------------------------------------------------------------

    def dispatch(self, body: dict[str, Any]) -> dict[str, Any]:
        method, params = body["method"], body.get("params", {})
        self.calls.append((method, params))
        handler = getattr(self, f"do_{method}", None)
        if handler is None:
            return {
                "jsonrpc": "2.0",
                "id": body["id"],
                "error": {"code": -32601, "message": method},
            }
        outcome = handler(params)
        if isinstance(outcome, tuple):
            return {
                "jsonrpc": "2.0",
                "id": body["id"],
                "error": {
                    "code": 5,
                    "message": "system error",
                    "data": {"error_string": outcome[0]},
                },
            }
        return {"jsonrpc": "2.0", "id": body["id"], "result": outcome}

    def selected(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        ids = params.get("ids")
        if ids is None:
            return self.torrents
        return [item for item in self.torrents if item["hash_string"] in ids]

    def do_torrent_get(self, params: dict[str, Any]) -> dict[str, Any]:
        fields = params["fields"]
        return {
            "torrents": [
                {key: value for key, value in item.items() if key in fields}
                for item in self.selected(params)
            ]
        }

    def do_torrent_add(self, params: dict[str, Any]) -> dict[str, Any]:
        source = params.get("metainfo") or params["filename"]
        new_hash = HASH if "metainfo" in params else OTHER_HASH
        if any(item["hash_string"] == new_hash for item in self.torrents):
            return {"torrent_duplicate": {"hash_string": new_hash, "id": 1, "name": "probe.bin"}}
        added = torrent(
            hash_string=new_hash,
            id=len(self.torrents) + 1,
            name="x" if "filename" in params else "probe.bin",
            download_dir=params.get("download_dir", "/downloads/complete"),
            status=0 if params.get("paused") else 4,
        )
        self.torrents.append(added)
        assert source
        return {
            "torrent_added": {"hash_string": new_hash, "id": added["id"], "name": added["name"]}
        }

    def do_torrent_start(self, params: dict[str, Any]) -> dict[str, Any]:
        for item in self.selected(params):
            item["status"] = 4
        return {}

    def do_torrent_stop(self, params: dict[str, Any]) -> dict[str, Any]:
        for item in self.selected(params):
            item["status"] = 0
        return {}

    def do_torrent_remove(self, params: dict[str, Any]) -> dict[str, Any]:
        gone = {item["hash_string"] for item in self.selected(params)}
        self.torrents = [item for item in self.torrents if item["hash_string"] not in gone]
        return {}

    def do_torrent_set(self, params: dict[str, Any]) -> dict[str, Any]:
        priorities = {"priority_low": -1, "priority_normal": 0, "priority_high": 1}
        for item in self.selected(params):
            for key, indices in params.items():
                for index in indices if key in priorities or key.startswith("files_") else []:
                    if key in priorities:
                        item["file_stats"][index]["priority"] = priorities[key]
                    else:
                        item["file_stats"][index]["wanted"] = key == "files_wanted"
        return {}

    def do_session_get(self, params: dict[str, Any]) -> dict[str, Any]:
        fields = params.get("fields")
        return {k: v for k, v in self.session.items() if fields is None or k in fields}

    def do_session_set(self, params: dict[str, Any]) -> dict[str, Any]:
        self.session.update(params)
        return {}

    def do_free_space(self, params: dict[str, Any]) -> dict[str, Any] | tuple[str]:
        if not params["path"].startswith("/downloads"):
            return ("No such file or directory",)
        return {"path": params["path"], "size_bytes": self.free[0], "total_size": self.free[1]}
