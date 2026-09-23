"""Named WireGuard exits: the generated Compose file, their numbering and what config.yaml takes."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from vibedpn import cli
from vibedpn.bootstrap import read_env, render_config, required_secrets, wg_uplink_secrets
from vibedpn.compose import (
    WG_UPLINKS_FILE,
    file_digest,
    refresh_wg_uplinks,
    render_wg_uplinks,
    wg_uplink_digest,
)
from vibedpn.config import Config
from vibedpn.engine.router import uplink_service, uplink_table, used_uplinks, wg_uplinks

from .conftest import home_config

PEER_TEXT = "[Interface]\nPrivateKey = x\n\n[Peer]\nPublicKey = y\n"


def wg_config(*names: str, default_upstream: str = "dpn") -> Config:
    raw: dict[str, Any] = home_config()
    raw["upstreams"]["wg"] = {name: {} for name in names}
    raw["routing"] = {"mode": "full", "default_upstream": default_upstream}
    return Config.model_validate(raw)


def test_each_name_extends_the_gateway_with_its_address_and_peer_file() -> None:
    text = render_wg_uplinks(wg_config("proton"))
    assert (
        "  wg-proton:\n    extends:\n      file: compose.yaml\n      service: wg-client\n" in text
    )
    assert "ipv4_address: 10.77.0.50" in text
    assert "source: ./secrets/wg-proton.conf" in text
    # the base service keeps its own profile; this one carries the profile a home box activates
    assert "      - wg-uplink" in text


def test_each_exit_carries_the_fingerprint_of_its_own_peer_file() -> None:
    """It overrides the one of wg-client it extends: a new file of this exit recreates it alone."""
    text = render_wg_uplinks(wg_config("proton"))
    variable = wg_uplink_digest("proton")
    assert f"    environment:\n      VIBEDPN_CONFIG_DIGEST: ${{{variable}:-}}\n" in text


def test_a_new_file_for_an_exit_refreshes_its_fingerprint_at_once(tmp_path: Path) -> None:
    """`uplink add` runs with sudo and can read the file; `vibedpn up` after it may not."""
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    config = Config.model_validate(home_config())
    (tmp_path / "config.yaml").write_text(render_config(config), encoding="utf-8")
    peer = tmp_path / "provider.conf"
    fingerprints = []
    for text in (PEER_TEXT, PEER_TEXT + "# the provider moved the server\n"):
        peer.write_text(text, encoding="utf-8")
        answer = CliRunner().invoke(
            cli.app, ["uplink", "add", "work", str(peer), "--dir", str(tmp_path)]
        )
        assert answer.exit_code == 0, answer.output
        stored = file_digest(tmp_path / "secrets" / "wg-work.conf")
        assert read_env(tmp_path / ".env")[wg_uplink_digest("work")] == stored
        fingerprints.append(stored)
    assert fingerprints[0] != fingerprints[1]


def test_the_numbering_follows_the_sorted_names() -> None:
    uplinks = wg_uplinks(wg_config("proton", "mullvad"))
    assert [uplink.gateway for uplink in uplinks.values()] == ["10.77.0.50", "10.77.0.51"]
    assert [uplink.mark for uplink in uplinks.values()] == [0x50, 0x51]
    assert [uplink.table for uplink in uplinks.values()] == [7750, 7751]
    assert list(uplinks) == ["mullvad", "proton"]


def test_no_name_is_an_empty_file_that_still_exists(tmp_path: Path) -> None:
    config = Config.model_validate(home_config())
    assert render_wg_uplinks(config).endswith("services: {}\n")
    assert refresh_wg_uplinks(tmp_path, config) == tmp_path / WG_UPLINKS_FILE
    assert (tmp_path / WG_UPLINKS_FILE).is_file()


def test_the_peer_file_is_required_but_never_generated() -> None:
    config = wg_config("proton")
    assert wg_uplink_secrets(config) == ["wg-proton.conf"]
    assert "wg-proton.conf" in required_secrets(config)


def test_the_name_becomes_a_routing_key_and_a_service() -> None:
    config = wg_config("proton", default_upstream="wg-proton")
    assert "wg-proton" in uplink_table(config)
    assert uplink_service("wg-proton") == "wg-proton"
    # routing.mode full through it: the key is the one the router builds a table for
    assert "wg-proton" in used_uplinks(config)


def test_a_name_that_no_file_system_or_service_would_take_is_refused() -> None:
    raw: dict[str, Any] = home_config()
    raw["upstreams"]["wg"] = {"Proton VPN": {}}
    with pytest.raises(ValidationError, match="not a usable name"):
        Config.model_validate(raw)


def test_routing_refuses_an_uplink_the_box_does_not_run() -> None:
    with pytest.raises(ValidationError, match="not an enabled uplink"):
        wg_config("proton", default_upstream="wg-mullvad")
    with pytest.raises(ValidationError, match="is not an uplink"):
        wg_config("proton", default_upstream="warp")
    with pytest.raises(ValidationError, match="not an enabled uplink"):
        wg_config("proton", default_upstream="tor")  # an uplink kind, but this box has it off
