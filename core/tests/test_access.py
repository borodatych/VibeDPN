"""The access server: config, keys, the list of people, links, rendering, router and firewall."""

import json
import stat
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from pydantic import ValidationError

from vibedpn.atomic import write_private
from vibedpn.config import DIGEST_ACCESS, DIGEST_CORE, Config, Profile
from vibedpn.engine import access
from vibedpn.engine.access import (
    CONFIG_FILE,
    HEALTH_EMAIL,
    HEALTH_FILE,
    INBOUND_TAG,
    PEOPLE_FILE,
    PEOPLE_TABLE_FILE,
    SERVER_FILE,
    AccessError,
    PersonExistsError,
    PersonNameError,
    PersonNotFoundError,
    add_person,
    decode_key,
    encode_key,
    ensure_access,
    generate_keys,
    list_people,
    person_link,
    public_key,
    remove_person,
    render_people_table,
    render_server,
)
from vibedpn.engine.router import ACCESS_UID, firewall_ruleset, router_ruleset
from vibedpn.engine.xray import parse_share_link


def home_raw(**access_fields: object) -> dict[str, Any]:
    return {
        "version": 1,
        "role": "home",
        "network": {
            "lan_interface": "eth0",
            "lan_address": "192.168.1.50",
            "lan_subnet": "192.168.1.0/24",
        },
        "routing": {"mode": "full", "default_upstream": "dpn"},
        "upstreams": {"dpn": {"enabled": True}},
        "access": {"enabled": True, "address": "home.example.org", **access_fields},
    }


def home(**access_fields: object) -> Config:
    return Config.model_validate(home_raw(**access_fields))


def vps(**access_fields: object) -> Config:
    return Config.model_validate(
        {
            "version": 1,
            "role": "vps",
            "provider": {"enabled": True},
            "wg_server": {"endpoint": "vps.example.org"},
            "access": {"enabled": True, **access_fields},
        }
    )


def dirs(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "secrets", tmp_path / "data" / "access"


# --- config ------------------------------------------------------------------------------------


def test_defaults_are_port_443_and_a_cover_site_that_works() -> None:
    config = vps()
    assert (config.access.port, config.access.target) == (443, "dl.google.com")
    assert config.access_address() == "vps.example.org"  # a VPS falls back to its endpoint


def test_a_box_at_home_must_name_its_address() -> None:
    with pytest.raises(ValidationError, match=r"access\.address: required"):
        Config.model_validate({**home_raw(), "access": {"enabled": True}})
    assert home().access_address() == "home.example.org"


@pytest.mark.parametrize(
    ("field", "value"), [("address", "not a host!"), ("target", "no spaces.com ")]
)
def test_address_and_target_are_checked(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        vps(**{field: value})


def test_the_profile_is_on_both_roles_only_when_enabled() -> None:
    assert Profile.ACCESS in home().compose_profiles()
    assert Profile.ACCESS in vps().compose_profiles()
    assert Profile.ACCESS not in vps(enabled=False).compose_profiles()
    assert "access" in home().digest_services()


def test_the_digest_follows_what_the_server_reads_and_not_the_links() -> None:
    before = home().config_digests()
    assert home(port=8443).config_digests()[DIGEST_ACCESS] != before[DIGEST_ACCESS]
    assert home(target="www.apple.com").config_digests()[DIGEST_ACCESS] != before[DIGEST_ACCESS]
    # the address only goes into links: nothing restarts for it
    assert home(address="other.example.org").config_digests() == before
    # turning the server on changes core's fingerprint too: core renders the server's files
    off = home(enabled=False, address="home.example.org").config_digests()
    assert off[DIGEST_ACCESS] != before[DIGEST_ACCESS]
    assert off[DIGEST_CORE] != before[DIGEST_CORE]


# --- keys --------------------------------------------------------------------------------------


def test_keys_are_x25519_in_base64url_without_padding() -> None:
    keys = generate_keys()
    assert "=" not in keys.private_key and len(keys.private_key) == 43
    raw = decode_key(keys.private_key)
    expected = X25519PrivateKey.from_private_bytes(raw).public_key().public_bytes_raw()
    assert public_key(keys) == encode_key(expected)
    assert len(keys.short_id) == 16 and int(keys.short_id, 16) >= 0


@pytest.mark.parametrize("text", ["", "not*base64", encode_key(b"short")])
def test_a_key_that_is_not_32_bytes_is_refused(text: str) -> None:
    with pytest.raises(AccessError):
        decode_key(text)


# --- files, people, links ----------------------------------------------------------------------


def test_nothing_is_rendered_while_the_server_is_off(tmp_path: Path) -> None:
    secrets, data = dirs(tmp_path)
    assert ensure_access(vps(enabled=False), secrets, data, owner=None) is None
    assert not data.exists()


def test_the_server_files_are_private_and_the_key_survives_restarts(tmp_path: Path) -> None:
    secrets, data = dirs(tmp_path)
    files = ensure_access(vps(), secrets, data, owner=None)
    assert files is not None and files.people == 0
    for name in (CONFIG_FILE, HEALTH_FILE, PEOPLE_TABLE_FILE):
        assert stat.S_IMODE((data / name).stat().st_mode) == 0o600, name
    assert stat.S_IMODE(data.stat().st_mode) == 0o700
    first = (secrets / "access" / SERVER_FILE).read_text()
    ensure_access(vps(), secrets, data, owner=None)
    assert (secrets / "access" / SERVER_FILE).read_text() == first


def test_a_damaged_key_is_an_error_never_a_new_key(tmp_path: Path) -> None:
    secrets, data = dirs(tmp_path)
    ensure_access(vps(), secrets, data, owner=None)
    (secrets / "access" / SERVER_FILE).write_text("{broken")
    with pytest.raises(AccessError, match="restore it from a backup"):
        ensure_access(vps(), secrets, data, owner=None)
    assert (secrets / "access" / SERVER_FILE).read_text() == "{broken"


def test_a_person_gets_a_link_our_own_uplink_reads(tmp_path: Path) -> None:
    secrets, data = dirs(tmp_path)
    person, link = add_person(home(), secrets, data, "anna", owner=None)
    server = parse_share_link(link)
    keys = access.load_keys(secrets / "access")
    assert (server.uuid, server.host, server.port) == (person.id, "home.example.org", 443)
    assert (server.security, server.flow, server.fingerprint) == (
        "reality",
        "xtls-rprx-vision",
        "chrome",
    )
    assert (server.sni, server.public_key, server.short_id) == (
        "dl.google.com",
        public_key(keys),
        keys.short_id,
    )
    assert server.remark == "anna"
    assert person_link(home(), secrets, "anna") == link
    assert (data / PEOPLE_TABLE_FILE).read_text() == f"anna\t{person.id}\n"


def test_names_are_checked_and_unique(tmp_path: Path) -> None:
    secrets, data = dirs(tmp_path)
    add_person(home(), secrets, data, "anna", owner=None)
    with pytest.raises(PersonExistsError):
        add_person(home(), secrets, data, "anna", owner=None)
    with pytest.raises(PersonNameError):
        add_person(home(), secrets, data, "Anna Smith", owner=None)
    with pytest.raises(PersonNameError):
        add_person(home(), secrets, data, HEALTH_EMAIL, owner=None)  # the service user's name


def test_removing_a_person_takes_them_out_of_the_server(tmp_path: Path) -> None:
    secrets, data = dirs(tmp_path)
    add_person(home(), secrets, data, "anna", owner=None)
    boris, _ = add_person(home(), secrets, data, "boris", owner=None)
    remove_person(home(), secrets, data, "anna", owner=None)
    assert [person.name for person in list_people(secrets)] == ["boris"]
    assert (data / PEOPLE_TABLE_FILE).read_text() == f"boris\t{boris.id}\n"
    emails = [
        client["email"]
        for client in json.loads((data / CONFIG_FILE).read_text())["inbounds"][1]["settings"][
            "clients"
        ]
    ]
    assert emails == [HEALTH_EMAIL, "boris"]
    with pytest.raises(PersonNotFoundError):
        remove_person(home(), secrets, data, "anna", owner=None)


def test_people_are_managed_only_while_the_server_is_on(tmp_path: Path) -> None:
    secrets, data = dirs(tmp_path)
    with pytest.raises(AccessError, match="access enable"):
        add_person(vps(enabled=False), secrets, data, "anna", owner=None)


def test_a_list_that_cannot_be_saved_puts_the_server_files_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secrets, data = dirs(tmp_path)
    anna, _ = add_person(home(), secrets, data, "anna", owner=None)

    def failing(path: Path, content: str, *, owner: int | None = None) -> bool:
        if path.name == PEOPLE_FILE:
            raise OSError(28, "No space left on device")
        return write_private(path, content, owner=owner)

    monkeypatch.setattr(access, "write_private", failing)
    with pytest.raises(OSError, match="No space"):
        add_person(home(), secrets, data, "boris", owner=None)
    assert (data / PEOPLE_TABLE_FILE).read_text() == f"anna\t{anna.id}\n"
    assert [person.name for person in list_people(secrets)] == ["anna"]


def test_the_table_is_sorted_by_name() -> None:
    now = "2026-09-23T00:00:00Z"
    people = [
        access.Person.model_validate({"name": name, "id": f"id-{name}", "created": now})
        for name in ("zoe", "anna")
    ]
    assert render_people_table(people) == "anna\tid-anna\nzoe\tid-zoe\n"


# --- what the server itself is told ------------------------------------------------------------


def server_of(config: Config) -> dict[str, Any]:
    rendered: dict[str, Any] = json.loads(render_server(config, generate_keys(), []))
    return rendered


def test_the_server_keeps_no_access_log_and_closes_the_box_to_the_people() -> None:
    server = server_of(home())
    assert server["log"]["access"] == "none"
    rules = server["routing"]["rules"]
    blocked = next(rule for rule in rules if rule.get("outboundTag") == "block")["ip"]
    assert {"127.0.0.0/8", "192.168.0.0/16", "10.0.0.0/8", "169.254.0.0/16"} <= set(blocked)
    health = next(i for i, rule in enumerate(rules) if rule.get("user") == [HEALTH_EMAIL])
    assert health < rules.index(next(rule for rule in rules if rule.get("outboundTag") == "block"))
    people = next(inbound for inbound in server["inbounds"] if inbound["tag"] == INBOUND_TAG)
    assert people["port"] == 443 and people["sniffing"]["enabled"] is True
    assert people["streamSettings"]["realitySettings"]["target"] == "dl.google.com:443"


def test_a_box_at_home_resolves_through_its_adguard_and_a_vps_through_its_host() -> None:
    assert server_of(home())["dns"]["servers"] == ["192.168.1.50"]
    assert server_of(vps())["dns"]["servers"] == ["localhost"]


# --- router and firewall -----------------------------------------------------------------------


def test_the_server_traffic_is_steered_like_a_device_but_its_answers_are_not() -> None:
    text = router_ruleset(home()) or ""
    chain = text[text.index("chain access_output") :]
    chain = chain[: chain.index("\n  }")]
    assert f"meta skuid != {ACCESS_UID} return" in chain
    # the answers to the people go back the way they came, before anything could mark them
    assert chain.index("ct direction reply return") < chain.index("jump steer")
    assert "fib daddr type local return" in chain
    assert f"meta skuid {ACCESS_UID} meta nfproto ipv6 ct direction original" in text
    off = router_ruleset(home(enabled=False, address="home.example.org")) or ""
    assert "access_output" not in off and str(ACCESS_UID) not in off


def test_a_vps_opens_the_port_of_the_server_only_when_it_runs() -> None:
    assert 'tcp dport 443 accept comment "access server"' in (firewall_ruleset(vps()) or "")
    assert 'tcp dport 8443 accept comment "access server"' in (
        firewall_ruleset(vps(port=8443)) or ""
    )
    assert "access server" not in (firewall_ruleset(vps(enabled=False)) or "")
