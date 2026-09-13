"""AdGuardHome.yaml: only core's keys change in a file AdGuard rewrote; foreign schema refused."""

import difflib
import stat
from pathlib import Path
from typing import Any

import pytest

from vibedpn.config import Config, parse_yaml
from vibedpn.engine.adguard import (
    CONF_FILE,
    HOST_NAME_STATE_FILE,
    AdguardError,
    adguard_text,
    ensure_adguard,
    password_hash,
)

from .conftest import client_config, vps_config

FIXTURE = Path(__file__).parent / "fixtures" / "adguard_v0_107_79.yaml"
HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ012345"


def lan_box(mode: str = "full") -> Config:
    raw = client_config()
    raw["routing"]["mode"] = mode
    return Config.model_validate(raw)


def as_data(text: str) -> dict[str, Any]:
    data = parse_yaml(text)
    assert isinstance(data, dict)
    return data


def test_a_new_file_carries_exactly_our_keys() -> None:
    data = as_data(adguard_text(None, lan_box(), HASH))
    assert data["schema_version"] == 34
    assert data["http"]["address"] == "192.168.1.50:3000"
    assert data["users"] == [{"name": "admin", "password": HASH}]
    assert data["dns"]["bind_hosts"] == ["192.168.1.50"]
    assert data["dns"]["port"] == 53
    assert data["dns"]["upstream_dns"] == ["https://dns.cloudflare.com/dns-query"]
    assert data["dns"]["aaaa_disabled"] is True
    assert as_data(adguard_text(None, lan_box("off"), HASH))["dns"]["aaaa_disabled"] is False


def test_the_file_adguard_rewrote_keeps_everything_but_our_keys() -> None:
    before = FIXTURE.read_text(encoding="utf-8")
    after = adguard_text(before, lan_box(), HASH)
    changed = [
        line
        for line in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0)
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    ]
    # The fixture already listens on the box address and port 3000, so http.address stays.
    assert sorted(changed) == sorted(
        [
            "-    password: $2b$12$FIXTUREfixtureFIXTUREfuQ7m0bq3WmOq3bqS8rK4cJwq0vY1n2Wy",
            f"+    password: {HASH}",
            "-    - 127.0.0.1",
            "+    - 192.168.1.50",
            "-  port: 5354",
            "+  port: 53",
            "-  aaaa_disabled: false",
            "+  aaaa_disabled: true",
            "-  rewrites: []",
            "+  rewrites:",
            "+    - domain: vibedpn.lan",
            "+      answer: 192.168.1.50",
            "+      enabled: true",
        ]
    )
    data = as_data(after)
    assert data["dns"]["ratelimit"] == 20 and "filters" in data
    assert adguard_text(after, lan_box(), HASH) == after  # a second start changes nothing


def test_a_user_added_in_the_adguard_ui_survives() -> None:
    before = FIXTURE.read_text(encoding="utf-8").replace(
        "users:\n", "users:\n  - name: guest\n    password: $2b$12$guest\n", 1
    )
    users = as_data(adguard_text(before, lan_box(), HASH))["users"]
    assert {"name": "guest", "password": "$2b$12$guest"} in users
    assert {"name": "admin", "password": HASH} in users


def test_a_foreign_schema_is_left_untouched() -> None:
    newer = FIXTURE.read_text(encoding="utf-8").replace("schema_version: 34", "schema_version: 35")
    with pytest.raises(AdguardError, match="schema_version 35"):
        adguard_text(newer, lan_box(), HASH)


def test_password_hash_comes_from_htpasswd() -> None:
    assert password_hash(f"# comment\nadmin:{HASH}\n") == HASH
    with pytest.raises(AdguardError, match="no entry for admin"):
        password_hash("root:$2b$12$x\n")


def test_ensure_writes_600_and_skips_boxes_without_adguard(tmp_path: Path) -> None:
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "htpasswd").write_text(f"admin:{HASH}\n", encoding="utf-8")
    (secrets / "adguard-core-password").write_text("core-secret-123", encoding="utf-8")
    conf = tmp_path / "conf"
    assert ensure_adguard(lan_box(), conf, secrets, tmp_path / "data") is True
    assert stat.S_IMODE((conf / CONF_FILE).stat().st_mode) == 0o600
    assert ensure_adguard(lan_box(), conf, secrets, tmp_path / "data") is False
    vps = Config.model_validate(vps_config())
    assert ensure_adguard(vps, tmp_path / "none", secrets, tmp_path / "data") is None
    raw = client_config()
    raw["dns"] = {"enabled": False}
    assert (
        ensure_adguard(Config.model_validate(raw), tmp_path / "none", secrets, tmp_path / "data")
        is None
    )
    assert not (tmp_path / "none").exists()


def rewrites_of(text: str) -> list[dict[str, Any]]:
    rewrites = as_data(text)["filtering"]["rewrites"]
    assert isinstance(rewrites, list)
    return rewrites


def test_the_box_name_points_at_the_lan_address() -> None:
    assert rewrites_of(adguard_text(None, lan_box(), HASH)) == [
        {"domain": "vibedpn.lan", "answer": "192.168.1.50", "enabled": True}
    ]


def test_a_renamed_box_replaces_only_its_own_rewrite() -> None:
    owner = {"domain": "nas.lan", "answer": "192.168.1.20", "enabled": True}
    existing = adguard_text(None, lan_box(), HASH).replace(
        "  rewrites:\n",
        "  rewrites:\n    - domain: nas.lan\n      answer: 192.168.1.20\n      enabled: true\n",
        1,
    )
    raw = client_config()
    raw["ui"] = {"host_name": "Box.Home."}
    renamed = Config.model_validate(raw)
    assert rewrites_of(adguard_text(existing, renamed, HASH, "vibedpn.lan")) == [
        owner,
        {"domain": "box.home", "answer": "192.168.1.50", "enabled": True},
    ]
    raw["ui"] = {"enabled": False, "host_name": "box.home"}
    assert rewrites_of(adguard_text(existing, Config.model_validate(raw), HASH, "vibedpn.lan")) == [
        owner
    ]


def test_ensure_records_the_published_name(tmp_path: Path) -> None:
    conf, secrets, data = tmp_path / "conf", tmp_path / "secrets", tmp_path / "data"
    secrets.mkdir()
    (secrets / "htpasswd").write_text(f"admin:{HASH}\n", encoding="utf-8")
    (secrets / "adguard-core-password").write_text("core-secret-123", encoding="utf-8")
    ensure_adguard(lan_box(), conf, secrets, data)
    assert (data / HOST_NAME_STATE_FILE).read_text(encoding="utf-8") == "vibedpn.lan\n"
    raw = client_config()
    raw["ui"] = {"host_name": "box.home"}
    ensure_adguard(Config.model_validate(raw), conf, secrets, data)
    domains = [
        entry["domain"] for entry in rewrites_of((conf / CONF_FILE).read_text(encoding="utf-8"))
    ]
    assert domains == ["box.home"]
    assert (data / HOST_NAME_STATE_FILE).read_text(encoding="utf-8") == "box.home\n"


def test_a_bad_box_name_is_refused() -> None:
    raw = client_config()
    raw["ui"] = {"host_name": "not a name"}
    with pytest.raises(ValueError, match="not a domain name"):
        Config.model_validate(raw)
