"""The settings.json of the client and its RPC, against the stand-in of a live daemon."""

import base64
import json
from pathlib import Path

import httpx
import pytest

from vibedpn.config import Config
from vibedpn.engine.transmission import (
    CONTAINER_COMPLETE,
    RpcClient,
    TorrentInputError,
    TorrentNotFoundError,
    TransmissionError,
    TransmissionUnavailableError,
    check_hash,
    check_metainfo,
    check_subdir,
    limit_params,
    read_rpc_password,
    settings_differ,
    settings_keys,
    settings_text,
)

from .conftest import client_config
from .torrents_fake import HASH, OTHER_HASH, PASSWORD, SESSION_ID, FakeTransmission


def config(**section: object) -> Config:
    return Config.model_validate({**client_config(), "torrents": {"enabled": True, **section}})


def rpc(fake: FakeTransmission, password: str = PASSWORD) -> RpcClient:
    return RpcClient(password, transport=fake.transport())


# --- settings.json ----------------------------------------------------------------------------


def test_the_rpc_stays_on_loopback_and_the_ports_follow_the_config() -> None:
    keys = settings_keys(config(peer_port=51999))
    assert keys["rpc-bind-address"] == "127.0.0.1"
    assert keys["peer-port"] == 51999
    assert keys["port-forwarding-enabled"] is False  # no UPnP or NAT-PMP
    assert keys["download-dir"] == CONTAINER_COMPLETE
    assert keys["speed-limit-down-enabled"] is False and "speed-limit-down" not in keys


def test_a_limit_is_written_with_its_number_and_a_removed_one_keeps_the_clients() -> None:
    keys = settings_keys(config(speed_limit_down=500))
    assert (keys["speed-limit-down"], keys["speed-limit-down-enabled"]) == (500, True)
    existing = json.dumps({**keys, "speed-limit-up": 77, "speed-limit-up-enabled": False})
    assert not settings_differ(existing, config(speed_limit_down=500))  # 77 is not ours to reset


def test_only_our_keys_change_in_a_file_the_client_rewrote() -> None:
    existing = json.dumps({"blocklist-enabled": True, "rpc-bind-address": "::", "peer-port": 1})
    text = json.loads(settings_text(existing, config()))
    assert text["blocklist-enabled"] is True  # the client's own
    assert text["rpc-bind-address"] == "127.0.0.1" and text["peer-port"] == 51413
    assert not settings_differ(json.dumps(text), config())


def test_the_limits_alone_do_not_make_a_file_differ_when_they_are_left_out() -> None:
    held = json.dumps(settings_keys(config()))
    assert settings_differ(held, config(speed_limit_up=80))
    assert not settings_differ(held, config(speed_limit_up=80), limits=False)
    assert settings_differ(held, config(peer_port=51999), limits=False)


def test_limits_are_handed_to_session_set_in_kilobytes() -> None:
    assert limit_params(config()) == {
        "speed_limit_down_enabled": False,
        "speed_limit_up_enabled": False,
    }
    assert limit_params(config(speed_limit_down=500, speed_limit_up=80)) == {
        "speed_limit_down_enabled": True,
        "speed_limit_up_enabled": True,
        "speed_limit_down": 500,
        "speed_limit_up": 80,
    }


@pytest.mark.parametrize("existing", [None, "", "not json", "[]"])
def test_a_missing_or_broken_file_is_replaced(existing: str | None) -> None:
    assert settings_differ(existing, config())
    assert not settings_differ(settings_text(existing, config()), config())


# --- the RPC ----------------------------------------------------------------------------------


def test_a_call_repeats_with_the_session_id_the_client_names() -> None:
    fake = FakeTransmission()
    assert rpc(fake).torrents(("hash_string",)) == [{"hash_string": HASH}]
    assert fake.session_checks == 1  # one 409, then the same request again
    assert len(fake.calls) == 1


def test_a_refused_password_is_unavailable_with_the_remedy() -> None:
    with pytest.raises(TransmissionUnavailableError, match="refused the password"):
        rpc(FakeTransmission(), "wrong").session()


def test_a_client_that_does_not_answer_is_unavailable() -> None:
    fake = FakeTransmission()
    fake.down = True
    with pytest.raises(TransmissionUnavailableError, match="does not answer"):
        rpc(fake).session()


def test_the_error_the_client_names_reaches_the_operator() -> None:
    fake = FakeTransmission()
    with pytest.raises(TransmissionError, match="refused nope"):
        rpc(fake).call("nope")
    assert rpc(fake).free_space("/elsewhere") is None  # a folder the client has not got
    assert rpc(fake).free_space("/downloads/complete") == (100 * 1024**3, 500 * 1024**3)


def test_an_unknown_torrent_is_not_found_and_nothing_is_sent_for_it() -> None:
    fake = FakeTransmission()
    with pytest.raises(TorrentNotFoundError):
        rpc(fake).act("torrent_stop", OTHER_HASH)
    assert [name for name, _ in fake.calls] == ["torrent_get"]


def test_a_hash_is_forty_hex_characters_in_lower_case() -> None:
    assert check_hash(HASH.upper()) == HASH
    for bad in ("12", "z" * 40, HASH + "0"):
        with pytest.raises(TorrentInputError):
            check_hash(bad)


@pytest.mark.parametrize("subdir", ["../x", "a//b", "/abs", ".", "a/./b", "a\\b"])
def test_a_folder_inside_the_downloads_never_leaves_them(subdir: str) -> None:
    with pytest.raises(TorrentInputError):
        check_subdir(subdir)
    assert check_subdir("films/2026") == "films/2026"
    assert check_subdir("") is None


def test_a_torrent_file_is_base64_of_a_bencoded_dictionary() -> None:
    good = base64.b64encode(b"d4:infod4:name1:aee").decode()
    assert check_metainfo(good) == good
    for bad in ("###", base64.b64encode(b"not a torrent").decode()):
        with pytest.raises(TorrentInputError):
            check_metainfo(bad)


def test_adding_names_one_source_and_a_folder_under_complete() -> None:
    fake = FakeTransmission()
    client = rpc(fake)
    with pytest.raises(TorrentInputError, match="exactly one"):
        client.add(magnet=None, metainfo=None, subdir=None, paused=False)
    with pytest.raises(TorrentInputError, match="not a magnet"):
        client.add(magnet="http://x", metainfo=None, subdir=None, paused=False)
    added, duplicate = client.add(
        magnet="magnet:?xt=urn:btih:" + OTHER_HASH, metainfo=None, subdir="films", paused=True
    )
    assert (added["hash_string"], duplicate) == (OTHER_HASH, False)
    method, params = fake.calls[-1]
    assert method == "torrent_add"
    assert params["download_dir"] == "/downloads/complete/films" and params["paused"] is True


def test_the_password_comes_from_secrets(tmp_path: Path) -> None:
    secrets = tmp_path
    with pytest.raises(TransmissionUnavailableError, match="cannot read"):
        read_rpc_password(secrets)
    (secrets / "transmission-rpc-pass").write_text("  \n", encoding="utf-8")
    with pytest.raises(TransmissionUnavailableError, match="empty"):
        read_rpc_password(secrets)
    (secrets / "transmission-rpc-pass").write_text("abc\n", encoding="utf-8")
    assert read_rpc_password(secrets) == "abc"


def test_the_stand_in_hands_out_the_session_id_the_tests_rely_on() -> None:
    response = httpx.Client(transport=FakeTransmission().transport()).post(
        "http://x/", auth=("vibedpn", PASSWORD), json={}
    )
    assert (
        response.status_code == 409 and response.headers["x-transmission-session-id"] == SESSION_ID
    )
