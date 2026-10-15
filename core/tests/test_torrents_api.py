"""``/torrents`` through the application, with a stand-in for the RPC of the client."""

import base64
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from vibedpn.api.app import create_app
from vibedpn.api.state import BoxState
from vibedpn.bootstrap import render_config
from vibedpn.config import Config, load_config
from vibedpn.engine.apply import APPLY, STORAGE_SCAN, read_task_reason, read_task_request
from vibedpn.engine.storage import DEVICES_FILE

from .conftest import client_config
from .torrents_fake import GIB, HASH, OTHER_HASH, PASSWORD, FakeTransmission

DEVICES = {
    "scanned_at": 1790000000.0,
    "devices": [
        {"uuid": "1234-ABCD", "label": "TORRENTS", "fstype": "exfat", "size": 2 * 10**12,
         "device": "/dev/sda1", "mountpoint": None, "supported": True},
        {"uuid": "AB12-CD34", "label": "EFI", "fstype": "vfat", "size": 536870912,
         "device": "/dev/nvme0n1p1", "mountpoint": "/boot/efi", "supported": False},
    ],
}  # fmt: skip


class Stand:
    def __init__(self, tmp_path: Path, **section: object) -> None:
        raw = {**client_config(), "torrents": {"enabled": True, **section}}
        self.config = Config.model_validate(raw)
        self.path = tmp_path / "config.yaml"
        self.path.write_text(render_config(self.config), encoding="utf-8")
        (tmp_path / "secrets").mkdir(mode=0o700)
        (tmp_path / "secrets" / "transmission-rpc-pass").write_text(PASSWORD, encoding="utf-8")
        self.data = tmp_path / "data"
        self.data.mkdir()
        self.fake = FakeTransmission()
        state = BoxState(self.config, self.path, apply=lambda _config: [])
        self.client = TestClient(
            create_app(
                self.config,
                state=state,
                secrets_dir=tmp_path / "secrets",
                data_dir=self.data,
                torrents_transport=self.fake.transport(),
            )
        )

    def devices(self) -> None:
        (self.data / DEVICES_FILE).write_text(json.dumps(DEVICES), encoding="utf-8")


@pytest.fixture
def stand(tmp_path: Path) -> Stand:
    return Stand(tmp_path)


def test_the_list_shows_what_the_panel_needs(stand: Stand) -> None:
    stand.fake.torrents[0].update(
        status=4, percent_done=0.42, rate_download=1000, rate_upload=20, eta=3600,
        upload_ratio=0.1,
    )  # fmt: skip
    body = stand.client.get("/torrents").json()
    assert body["rate_down"] == 1000 and body["rate_up"] == 20
    assert body["torrents"] == [
        {"id": HASH, "name": "probe.bin", "status": "downloading", "progress": 0.42,
         "rate_down": 1000, "rate_up": 20, "eta": 3600, "size": 16384, "ratio": 0.1,
         "error": None}
    ]  # fmt: skip


def test_unknown_values_are_none_and_an_error_is_its_phrase(stand: Stand) -> None:
    stand.fake.torrents[0].update(eta=-1, upload_ratio=-2, error=3, error_string="No space left")
    item = stand.client.get("/torrents").json()["torrents"][0]
    assert (item["eta"], item["ratio"], item["error"]) == (None, None, "No space left")


def test_every_status_has_a_name(stand: Stand) -> None:
    seen = []
    for number in range(7):
        stand.fake.torrents[0]["status"] = number
        seen.append(stand.client.get("/torrents").json()["torrents"][0]["status"])
    assert seen == [
        "stopped", "check_wait", "checking", "download_wait", "downloading", "seed_wait", "seeding"
    ]  # fmt: skip


def test_a_magnet_is_added_into_a_folder_and_a_duplicate_is_said(stand: Stand) -> None:
    body = {"magnet": f"magnet:?xt=urn:btih:{OTHER_HASH}", "subdir": "films", "paused": True}
    first = stand.client.post("/torrents", json=body)
    assert first.status_code == 201, first.text
    assert first.json() == {"id": OTHER_HASH, "name": "x", "duplicate": False}
    again = stand.client.post("/torrents", json=body)
    assert again.status_code == 200 and again.json()["duplicate"] is True
    detail = stand.client.get(f"/torrents/{OTHER_HASH}").json()
    assert detail["download_dir"] == "/srv/vibedpn/downloads/complete/films"  # as the host sees it
    assert detail["status"] == "stopped"


def test_a_torrent_file_is_added_by_its_base64(stand: Stand) -> None:
    raw = base64.b64encode(b"d4:infod4:name9:probe.bine").decode()
    stand.fake.torrents.clear()
    added = stand.client.post("/torrents", json={"torrent": raw})
    assert added.status_code == 201 and added.json()["id"] == HASH
    assert [item["id"] for item in stand.client.get("/torrents").json()["torrents"]] == [HASH]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"magnet": "magnet:?xt=a", "torrent": "ZA=="},
        {"magnet": "http://not-a-magnet"},
        {"torrent": "not base64 ###"},
        {"magnet": "magnet:?xt=a", "subdir": "../escape"},
        {"magnet": "magnet:?xt=a", "extra": 1},
    ],
)
def test_a_request_the_client_cannot_take_is_422(stand: Stand, body: dict[str, Any]) -> None:
    assert stand.client.post("/torrents", json=body).status_code == 422


def test_start_stop_and_remove_by_hash(stand: Stand) -> None:
    assert stand.client.post(f"/torrents/{HASH}/stop").status_code == 204
    assert stand.fake.torrents[0]["status"] == 0
    assert stand.client.post(f"/torrents/{HASH}/start").status_code == 204
    assert stand.fake.torrents[0]["status"] == 4
    assert stand.client.delete(f"/torrents/{HASH}?data=true").status_code == 204
    assert stand.fake.calls[-1] == (
        "torrent_remove",
        {"ids": [HASH], "delete_local_data": True},
    )
    assert stand.fake.torrents == []


def test_an_unknown_torrent_is_404_and_a_bad_hash_422(stand: Stand) -> None:
    for method, suffix in (("post", "/start"), ("delete", ""), ("get", "")):
        call = getattr(stand.client, method)
        assert call(f"/torrents/{OTHER_HASH}{suffix}").status_code == 404
        assert call(f"/torrents/12{suffix}").status_code == 422


def test_the_detail_has_files_peers_and_trackers(stand: Stand) -> None:
    stand.fake.torrents[0].update(
        file_stats=[{"bytes_completed": 500, "priority": 1, "wanted": False}],
        peers=[{"address": "203.0.113.5", "client_name": "qBittorrent 5.0", "progress": 0.5,
                "rate_to_client": 100, "rate_to_peer": 7, "flag_str": "TDE"}],
        tracker_stats=[{"announce": "http://t.example/announce", "host": "t.example",
                        "seeder_count": 12, "leecher_count": 0, "last_announce_succeeded": True,
                        "last_announce_result": "Success", "last_announce_time": 1790000000}],
    )  # fmt: skip
    body = stand.client.get(f"/torrents/{HASH}").json()
    assert body["files"] == [
        {"index": 0, "name": "probe.bin", "size": 16384, "done": 500, "wanted": False,
         "priority": "high"}
    ]  # fmt: skip
    assert body["peers"] == [
        {"address": "203.0.113.5", "client": "qBittorrent 5.0", "progress": 0.5,
         "rate_down": 100, "rate_up": 7, "flags": "TDE"}
    ]  # fmt: skip
    assert body["trackers"][0]["seeders"] == 12 and body["trackers"][0]["leechers"] == 0


def test_files_are_wanted_or_not_and_get_a_priority(stand: Stand) -> None:
    done = stand.client.put(
        f"/torrents/{HASH}/files", json={"indices": [0], "wanted": False, "priority": "low"}
    )
    assert done.status_code == 204
    assert stand.fake.torrents[0]["file_stats"][0] == {
        "bytes_completed": 0, "priority": -1, "wanted": False
    }  # fmt: skip
    for body in (
        {"indices": [], "wanted": True},  # an empty list would mean every file to Transmission
        {"indices": [0]},
        {"indices": [-1], "wanted": True},
        {"indices": [0], "priority": "urgent"},
    ):
        assert stand.client.put(f"/torrents/{HASH}/files", json=body).status_code == 422


def test_the_session_limits_are_set_live_and_kept_in_the_config(stand: Stand) -> None:
    shown = stand.client.get("/torrents/session").json()
    assert shown["speed_limit_down_enabled"] is False
    changed = stand.client.put(
        "/torrents/session", json={"speed_limit_down": 500, "speed_limit_down_enabled": True}
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["speed_limit_down"] == 500
    assert stand.fake.session["speed_limit_down_enabled"] is True
    assert load_config(stand.path).torrents.speed_limit_down == 500
    off = stand.client.put("/torrents/session", json={"speed_limit_down_enabled": False})
    assert off.json()["speed_limit_down"] == 500  # the number stays with the client
    assert load_config(stand.path).torrents.speed_limit_down is None


def test_a_limit_switched_on_without_a_number_is_refused(stand: Stand) -> None:
    stand.fake.session["speed_limit_up"] = 0
    refused = stand.client.put("/torrents/session", json={"speed_limit_up_enabled": True})
    assert refused.status_code == 422 and "needs a number" in refused.text
    assert stand.client.put("/torrents/session", json={"unknown": 1}).status_code == 422


def test_the_storage_shows_space_and_the_disks_the_host_saw(stand: Stand) -> None:
    stand.devices()
    body = stand.client.get("/torrents/storage").json()
    assert body["download_dir"] == "/srv/vibedpn/downloads" and body["egress"] == "direct"
    assert (body["free_bytes"], body["total_bytes"]) == (100 * GIB, 500 * GIB)
    assert body["storage"] == {"configured": False, "uuid": None, "mounted": False}
    assert [item["uuid"] for item in body["devices"]] == ["1234-ABCD", "AB12-CD34"]
    assert body["scanned_at"] == 1790000000.0 and body["state"]["pending"] is False


def test_asking_for_a_fresh_look_leaves_a_request_for_the_host(stand: Stand) -> None:
    body = stand.client.get("/torrents/storage?refresh=true").json()
    assert body["state"]["pending"] is True
    assert read_task_request(stand.data, STORAGE_SCAN) is not None
    assert read_task_reason(stand.data, STORAGE_SCAN) == "storage"


def test_picking_a_disk_writes_the_config_and_asks_the_host_to_apply(stand: Stand) -> None:
    stand.devices()
    answer = stand.client.put("/torrents/storage", json={"uuid": "1234-abcd"})
    assert answer.status_code == 202, answer.text
    saved = load_config(stand.path).torrents
    assert (saved.storage.uuid, saved.storage.fstype) == ("1234-ABCD", "exfat")
    assert saved.download_dir == "/srv/vibedpn/usb/downloads"
    assert answer.json()["state"]["pending"] is True
    assert read_task_request(stand.data, APPLY) is not None
    assert [item["current"] for item in answer.json()["devices"]] == [True, False]
    back = stand.client.put("/torrents/storage", json={"uuid": None})
    assert back.status_code == 202
    assert load_config(stand.path).torrents.download_dir == "/srv/vibedpn/downloads"
    assert load_config(stand.path).torrents.storage.uuid is None


def test_a_disk_the_host_did_not_see_or_cannot_use_is_refused(stand: Stand) -> None:
    assert stand.client.put("/torrents/storage", json={"uuid": "1234-ABCD"}).status_code == 422
    stand.devices()
    assert stand.client.put("/torrents/storage", json={"uuid": "FFFF-FFFF"}).status_code == 422
    refused = stand.client.put("/torrents/storage", json={"uuid": "AB12-CD34"})
    assert refused.status_code == 422 and "vfat" in refused.text
    assert load_config(stand.path).torrents.storage.uuid is None
    assert read_task_request(stand.data, APPLY) is None


def test_picking_the_same_disk_again_asks_for_nothing(tmp_path: Path) -> None:
    chosen = Stand(
        tmp_path,
        storage={"uuid": "1234-ABCD", "fstype": "exfat"},
        download_dir="/srv/vibedpn/usb/downloads",
    )
    chosen.devices()
    assert chosen.client.put("/torrents/storage", json={"uuid": "1234-ABCD"}).status_code == 202
    assert read_task_request(chosen.data, APPLY) is None


def test_the_storage_page_survives_a_client_that_is_not_up(stand: Stand) -> None:
    stand.fake.down = True
    body = stand.client.get("/torrents/storage").json()
    assert body["free_bytes"] is None and body["download_dir"] == "/srv/vibedpn/downloads"


def test_a_client_that_does_not_answer_is_503_with_the_remedy(stand: Stand) -> None:
    stand.fake.down = True
    answer = stand.client.get("/torrents")
    assert answer.status_code == 503 and "does not answer" in answer.json()["detail"]


def test_a_client_that_is_off_is_503_everywhere(tmp_path: Path) -> None:
    raw = client_config()
    config = Config.model_validate(raw)
    path = tmp_path / "config.yaml"
    path.write_text(render_config(config), encoding="utf-8")
    client = TestClient(create_app(config, state=BoxState(config, path, apply=lambda _c: [])))
    for method, url in (
        ("get", "/torrents"),
        ("get", "/torrents/session"),
        ("get", "/torrents/storage"),
        ("get", f"/torrents/{HASH}"),
        ("post", f"/torrents/{HASH}/stop"),
    ):
        answer = getattr(client, method)(url)
        assert answer.status_code == 503 and "torrents enable" in answer.json()["detail"], url


def test_a_missing_password_is_503_not_a_crash(tmp_path: Path) -> None:
    stand = Stand(tmp_path)
    (tmp_path / "secrets" / "transmission-rpc-pass").unlink()
    answer = stand.client.get("/torrents")
    assert answer.status_code == 503 and "transmission-rpc-pass" in answer.json()["detail"]


def test_a_refusal_of_the_client_is_502(stand: Stand) -> None:
    stand.fake.torrents[0]["status"] = 4

    def failing(_params: dict[str, Any]) -> tuple[str]:
        return ("permission denied",)

    stand.fake.do_torrent_stop = failing  # type: ignore[method-assign,assignment]
    answer = stand.client.post(f"/torrents/{HASH}/stop")
    assert answer.status_code == 502 and "permission denied" in answer.json()["detail"]
