"""vibedpn doctor on a box with the torrent client: its disk, RPC, folder, space and exit."""

from pathlib import Path

import pytest

from vibedpn.bootstrap import render_env
from vibedpn.config import Config, Profile
from vibedpn.doctor import (
    GIB,
    TorrentsFacts,
    Verdict,
    _env_matches,
    dir_writable_by_client,
    evaluate,
)

from .conftest import client_config
from .test_doctor import by_name, facts


def torrents_box(**section: object) -> Config:
    raw = {**client_config(), "torrents": {"enabled": True, **section}}
    return Config.model_validate(raw)


def results(config: Config, torrents: TorrentsFacts) -> dict[str, tuple[Verdict, str]]:
    found = by_name(evaluate(facts(config=config, torrents=torrents)))
    return {name: (item.verdict, item.detail) for name, item in found.items()}


HEALTHY = TorrentsFacts(rpc="", writable=True, free_bytes=100 * GIB, mounted=None, chain=None)


def test_a_healthy_client_has_four_green_lines() -> None:
    found = results(torrents_box(), HEALTHY)
    assert {name: found[name][0] for name in found if name.startswith("torrents")} == {
        "torrents rpc": Verdict.OK,
        "torrents folder": Verdict.OK,
        "torrents space": Verdict.OK,
    }


def test_a_client_that_is_off_is_not_checked() -> None:
    config = Config.model_validate(client_config())
    assert not [name for name in results(config, HEALTHY) if name.startswith("torrents")]


def test_an_rpc_that_does_not_answer_fails_with_the_reason() -> None:
    found = results(torrents_box(), TorrentsFacts(rpc="Transmission does not answer"))
    assert found["torrents rpc"] == (Verdict.FAIL, "Transmission does not answer")


def test_a_folder_the_client_cannot_write_fails() -> None:
    found = results(torrents_box(), TorrentsFacts(writable=False))
    assert found["torrents folder"][0] is Verdict.FAIL


def test_free_space_is_compared_with_the_threshold_of_the_config() -> None:
    low = TorrentsFacts(free_bytes=3 * GIB)
    assert results(torrents_box(min_free_gib=5), low)["torrents space"][0] is Verdict.FAIL
    assert results(torrents_box(min_free_gib=2), low)["torrents space"][0] is Verdict.OK
    assert (
        results(torrents_box(min_free_gib=0), TorrentsFacts(free_bytes=0))["torrents space"][0]
        is Verdict.OK
    )


@pytest.mark.parametrize(
    ("mounted", "verdict"), [(True, Verdict.OK), (False, Verdict.FAIL), (None, Verdict.WARN)]
)
def test_the_download_disk_must_be_mounted(mounted: bool | None, verdict: Verdict) -> None:
    config = torrents_box(
        storage={"uuid": "1234-ABCD", "fstype": "exfat"}, download_dir="/srv/vibedpn/usb/downloads"
    )
    found = results(config, TorrentsFacts(mounted=mounted))
    assert found["torrents disk"][0] is verdict
    assert "torrents disk" not in results(torrents_box(), TorrentsFacts(mounted=True))


def test_the_exit_of_the_client_is_checked_in_the_router() -> None:
    assert "torrents egress" not in results(torrents_box(), HEALTHY)
    missing = results(torrents_box(egress="vps"), TorrentsFacts(chain=False))
    assert missing["torrents egress"][0] is Verdict.FAIL
    assert "directly" in missing["torrents egress"][1]
    assert results(torrents_box(egress="vps"), TorrentsFacts(chain=True))["torrents egress"] == (
        Verdict.OK,
        "the client leaves through vps",
    )


def test_tor_is_allowed_with_a_warning() -> None:
    raw = {**client_config(), "upstreams": {"vps": {"enabled": True}, "tor": {"enabled": True}}}
    config = Config.model_validate({**raw, "torrents": {"enabled": True, "egress": "tor"}})
    found = results(config, TorrentsFacts(chain=True))
    assert found["torrents egress"][0] is Verdict.WARN and "TCP only" in found["torrents egress"][1]


def test_writability_is_the_clients_not_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "complete"
    assert dir_writable_by_client(folder) is None
    folder.mkdir()
    folder.chmod(0o755)
    assert dir_writable_by_client(folder) is False  # no write for others
    folder.chmod(0o775)
    assert dir_writable_by_client(folder) is False  # a group is not the client either
    folder.chmod(0o777)
    assert dir_writable_by_client(folder) is True  # anybody may
    # the folder belongs to the client: the owner's bit decides
    monkeypatch.setattr("vibedpn.doctor.TRANSMISSION_UID", folder.stat().st_uid)
    folder.chmod(0o555)
    assert dir_writable_by_client(folder) is False
    folder.chmod(0o755)
    assert dir_writable_by_client(folder) is True


def test_a_held_back_client_is_not_a_stale_env(tmp_path: Path) -> None:
    config = torrents_box(
        storage={"uuid": "1234-ABCD", "fstype": "exfat"}, download_dir="/srv/vibedpn/usb/downloads"
    )
    env = tmp_path / ".env"
    held = render_env(config, {}, None, [Profile.TORRENTS])
    env.write_text(held, encoding="utf-8")
    assert _env_matches(env, config)
    env.write_text(held.replace("ui", "ui,wifi"), encoding="utf-8")
    assert not _env_matches(env, config)  # any other difference still counts
    plain = torrents_box()  # without a disk the profile is never held back
    env.write_text(render_env(plain, {}, None, [Profile.TORRENTS]), encoding="utf-8")
    assert not _env_matches(env, plain)
