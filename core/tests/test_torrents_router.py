"""The torrent client's traffic: steered by its uid into the sticky slot of torrents.egress."""

from pathlib import Path
from typing import Any

import pytest

from vibedpn.config import Config, parse_yaml
from vibedpn.engine.router import (
    Uplink,
    exit_plan,
    router_ruleset,
    sticky_slot,
    sticky_uplinks,
    torrents_uplink,
    uplink_table,
    used_uplinks,
)
from vibedpn.engine.transmission import TRANSMISSION_UID

from .conftest import client_config, home_config

COMPOSE = Path(__file__).resolve().parents[2] / "compose.yaml"


def box(raw: dict[str, Any], **section: object) -> Config:
    return Config.model_validate({**raw, "torrents": {"enabled": True, **section}})


def test_direct_egress_adds_no_rule_and_no_uplink() -> None:
    config = box(client_config())
    assert torrents_uplink(config) is None
    ruleset = router_ruleset(config)
    assert ruleset is not None and "torrents_output" not in ruleset
    assert str(TRANSMISSION_UID) not in ruleset
    assert used_uplinks(config) == ["vps"]  # routing.mode full, nothing of the client's


def test_a_client_that_is_off_is_not_steered() -> None:
    raw = {**client_config(), "torrents": {"enabled": False, "egress": "vps"}}
    config = Config.model_validate(raw)
    ruleset = router_ruleset(config)
    assert torrents_uplink(config) is None
    assert ruleset is not None and "torrents_output" not in ruleset


def test_the_uid_of_the_client_leaves_through_the_sticky_slot_of_its_uplink() -> None:
    raw = home_config()  # routing off: the client alone needs the uplink
    raw["upstreams"] = {"dpn": {"enabled": True}, "tor": {"enabled": True}}
    config = box(raw, egress="dpn")
    assert torrents_uplink(config) == "dpn"
    assert used_uplinks(config) == ["dpn"]
    slot = sticky_slot(Uplink(mark=0x20, table=7720, gateway="10.77.0.20"))
    assert sticky_uplinks(config) == {"dpn": slot}
    ruleset = router_ruleset(config)
    assert ruleset is not None
    chain = ruleset[ruleset.index("chain torrents_output") :].split("chain forward")[0]
    assert "type route hook output priority mangle" in chain
    assert f"meta skuid != {TRANSMISSION_UID} return" in chain
    assert "ct direction reply return" in chain  # peers that dialled in get their answers back
    assert "fib daddr type local return" in chain
    assert f"meta mark set {hex(slot.mark)}" in chain
    # nothing of the client's goes around the uplink over IPv6
    assert f"meta skuid {TRANSMISSION_UID} meta nfproto ipv6 ct direction original" in ruleset


def test_the_client_holds_when_its_exit_is_silent_whatever_failopen_says() -> None:
    raw = client_config()
    raw["routing"] = {"mode": "off", "default_upstream": "vps", "failopen": True}
    config = box(raw, egress="vps")
    plan = exit_plan(config, used_uplinks(config))
    assert set(plan.sticky) == {"vps"}  # a table of its own, with the kill-switch route
    assert plan.sticky["vps"].mark & 0x100


def test_a_named_wireguard_exit_is_a_valid_egress() -> None:
    raw = home_config()
    raw["upstreams"] = {"dpn": {"enabled": True}, "wg": {"work": {"enabled": True}}}
    config = box(raw, egress="wg-work")
    assert used_uplinks(config) == ["wg-work"]
    table: dict[str, Uplink] = uplink_table(config)
    ruleset = router_ruleset(config)
    assert ruleset is not None
    assert hex(sticky_slot(table["wg-work"]).mark) in ruleset


def test_compose_runs_the_client_as_the_uid_the_router_looks_for() -> None:
    compose = parse_yaml(COMPOSE.read_text(encoding="utf-8"))
    assert isinstance(compose, dict)
    service = compose["services"]["transmission"]
    assert service["environment"]["PUID"] == str(TRANSMISSION_UID)
    assert service["network_mode"] == "host"
    assert service["depends_on"]["core"]["condition"] == "service_healthy"
    assert service["profiles"] == ["torrents"]


@pytest.mark.parametrize("egress", ["vps", "dpn"])
def test_rendering_is_deterministic(egress: str) -> None:
    raw = home_config()
    raw["upstreams"] = {"dpn": {"enabled": True}, "vps": {"enabled": True}}
    raw["role"] = "client"
    del raw["provider"]
    config = box(raw, egress=egress)
    assert router_ruleset(config) == router_ruleset(config)
