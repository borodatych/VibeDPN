"""The torrents section: roles, egress, the disk, profiles, env and the rendered file."""

from collections.abc import Callable
from typing import Any

import pytest
from pydantic import ValidationError

from vibedpn.bootstrap import (
    Answers,
    HostFacts,
    build_config,
    generated_secrets,
    render_config,
    render_env,
    required_secrets,
)
from vibedpn.config import (
    DIGEST_TRANSMISSION,
    TORRENTS_USB_DIR,
    Config,
    Profile,
    Role,
    parse_yaml,
)

from .conftest import client_config, home_config, vps_config


def with_torrents(raw: dict[str, Any], **section: object) -> Config:
    return Config.model_validate({**raw, "torrents": {"enabled": True, **section}})


def test_the_client_is_off_by_default_and_adds_its_profile_when_on() -> None:
    assert Profile.TORRENTS not in Config.model_validate(home_config()).compose_profiles()
    config = with_torrents(home_config())
    assert config.compose_profiles()[-1] is Profile.TORRENTS
    assert config.env_vars()["VIBEDPN_TORRENTS_DIR"] == "/srv/vibedpn/downloads"
    assert "VIBEDPN_TORRENTS_DIR" not in Config.model_validate(home_config()).env_vars()


@pytest.mark.parametrize("raw", [home_config, client_config])
def test_both_lan_roles_may_run_it(raw: Callable[[], dict[str, Any]]) -> None:
    assert with_torrents(raw()).torrents.enabled


def test_a_vps_refuses_the_section_even_when_it_is_off() -> None:
    with pytest.raises(ValidationError, match="torrents: not part of role 'vps'"):
        Config.model_validate({**vps_config(), "torrents": {"enabled": False}})


def test_the_egress_is_direct_or_an_uplink_that_is_on() -> None:
    assert with_torrents(client_config()).torrents.egress == "direct"
    assert with_torrents(client_config(), egress="vps").torrents.egress == "vps"
    with pytest.raises(ValidationError, match=r"torrents\.egress: 'dpn' is not an enabled uplink"):
        with_torrents(client_config(), egress="dpn")
    with pytest.raises(ValidationError, match="not an uplink"):
        with_torrents(client_config(), egress="somewhere")
    raw = home_config()
    raw["upstreams"] = {"dpn": {"enabled": True}, "wg": {"work": {"enabled": True}}}
    assert with_torrents(raw, egress="wg-work").torrents.egress == "wg-work"


def test_an_egress_that_is_off_does_not_matter_while_the_client_is_off() -> None:
    raw = {**client_config(), "torrents": {"enabled": False, "egress": "tor"}}
    assert Config.model_validate(raw).torrents.egress == "tor"


@pytest.mark.parametrize("path", ["downloads", "/a/../b", "/a b", "/a/./b", "/a;rm", "/srv/$HOME"])
def test_the_folder_is_an_absolute_plain_path(path: str) -> None:
    with pytest.raises(ValidationError):
        with_torrents(home_config(), download_dir=path)


def test_the_disk_names_its_filesystem_and_its_folder_lies_on_it() -> None:
    storage = {"uuid": "1234-ABCD", "fstype": "exfat"}
    config = with_torrents(home_config(), storage=storage, download_dir=TORRENTS_USB_DIR)
    assert config.torrents.storage.uuid == "1234-ABCD"
    with pytest.raises(ValidationError, match="must be under /srv/vibedpn/usb"):
        with_torrents(home_config(), storage=storage)
    with pytest.raises(ValidationError, match="which is not set"):
        with_torrents(home_config(), download_dir=TORRENTS_USB_DIR)
    with pytest.raises(ValidationError, match="uuid and fstype are set together"):
        with_torrents(home_config(), storage={"uuid": "1234-ABCD"}, download_dir=TORRENTS_USB_DIR)
    with pytest.raises(ValidationError, match="is not a filesystem UUID"):
        with_torrents(home_config(), storage={"uuid": "sda1", "fstype": "ext4"})
    with pytest.raises(ValidationError, match="is not one of"):
        with_torrents(home_config(), storage={"uuid": "1234-ABCD", "fstype": "btrfs"})


@pytest.mark.parametrize(
    "uuid",
    ["1234-ABCD", "01D6A5B3C4D5E6F7", "6f8c1f0e-1b9d-4c53-8a0b-3d5a0f8e2c11"],
)
def test_the_uuids_blkid_prints_are_accepted(uuid: str) -> None:
    with_torrents(
        home_config(),
        storage={"uuid": uuid, "fstype": "ext4"},
        download_dir=TORRENTS_USB_DIR,
    )


def test_limits_are_positive_numbers_or_none() -> None:
    assert with_torrents(home_config(), speed_limit_down=500).torrents.speed_limit_up is None
    with pytest.raises(ValidationError):
        with_torrents(home_config(), speed_limit_down=0)


def test_the_rendered_file_reads_back_to_the_same_box() -> None:
    config = with_torrents(
        client_config(),
        egress="vps",
        speed_limit_up=100,
        peer_port=51999,
        min_free_gib=20,
        storage={"uuid": "01D6A5B3C4D5E6F7", "fstype": "ntfs"},
        download_dir=f"{TORRENTS_USB_DIR}/films",
    )
    text = render_config(config)
    assert 'uuid: "01D6A5B3C4D5E6F7"' in text  # quoted: all digits would be a number in YAML
    assert Config.model_validate(parse_yaml(text)) == config


def test_a_vps_file_has_no_torrents_section() -> None:
    assert "torrents:" not in render_config(Config.model_validate(vps_config()))


def test_init_with_the_flag_turns_it_on_for_a_lan_role_and_makes_its_password() -> None:
    facts = HostFacts(None, True)
    assert (
        Profile.TORRENTS
        not in build_config(Answers(Role.VPS, endpoint="v.example.com"), facts).compose_profiles()
    )
    config = with_torrents(client_config())
    assert "transmission-rpc-pass" in generated_secrets(config)
    assert "transmission-rpc-pass" in required_secrets(config)
    assert "transmission-rpc-pass" not in required_secrets(Config.model_validate(client_config()))


def test_the_fingerprint_of_the_client_follows_what_its_file_holds() -> None:
    off = Config.model_validate(client_config()).config_digests()
    on = with_torrents(client_config()).config_digests()
    assert off[DIGEST_TRANSMISSION] != on[DIGEST_TRANSMISSION]
    limited = with_torrents(client_config(), speed_limit_down=300).config_digests()
    assert limited[DIGEST_TRANSMISSION] == on[DIGEST_TRANSMISSION]  # the limits are live


def test_a_profile_can_be_kept_off_in_the_env() -> None:
    config = with_torrents(client_config())

    def profiles(text: str) -> list[str]:
        line = next(item for item in text.splitlines() if item.startswith("COMPOSE_PROFILES="))
        return line.removeprefix("COMPOSE_PROFILES=").split(",")

    held = render_env(config, {}, None, [Profile.TORRENTS])
    assert "torrents" not in profiles(held)
    assert "VIBEDPN_TORRENTS_DIR=" in held  # the rest of the env is what the config says
    assert profiles(render_env(config, {}))[-1] == "torrents"
