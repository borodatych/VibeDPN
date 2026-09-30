"""Sticky channels (decision 33): the traffic of a rule never moves to routing.fallback; a silent
exit holds it, whatever failopen says — a new exit address mid-session costs an account tied to a
country more than an outage does."""

from __future__ import annotations

from ipaddress import IPv4Address
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from vibedpn.api.uplink import UplinkWatchers
from vibedpn.bootstrap import render_config
from vibedpn.config import Config, Upstream, load_config
from vibedpn.config_edit import set_domain_rule
from vibedpn.engine.resolver import channel_set
from vibedpn.engine.router import (
    ALL_SLOTS,
    UPLINKS,
    ExitPlan,
    Uplink,
    apply_router,
    exit_for,
    exit_plan,
    router_ruleset,
    smart_marks,
    sticky_slot,
    sticky_uplinks,
)

from .conftest import home_config
from .test_lan_router import fake_host

VPS, TOR = UPLINKS[Upstream.VPS], UPLINKS[Upstream.TOR]
CLAUDE = {"domain": "claude.ai", "via": "tor", "sticky": True}


def smart_box(*domains: dict[str, Any], failopen: bool = False, **routing: object) -> Config:
    raw: dict[str, Any] = home_config()
    raw["upstreams"] = {"dpn": {"enabled": True}, "tor": {"enabled": True}}
    raw["routing"] = {
        "mode": "smart",
        "default_upstream": "dpn",
        "failopen": failopen,
        "fallback": ["dpn"],
        "domains": list(domains),
        **routing,
    }
    return Config.model_validate(raw)


def test_a_sticky_channel_is_a_set_and_a_mark_of_its_own() -> None:
    config = smart_box(CLAUDE, {"domain": "rutracker.org", "via": "tor"})
    assert config.routing is not None
    sticky, plain = config.routing.domains
    assert (channel_set(sticky), channel_set(plain)) == ("smart_tor_sticky", "smart_tor")
    marks = {mark.name: mark.mark for mark in smart_marks(config)}
    assert marks == {"smart_tor": "0x60", "smart_tor_sticky": "0x160"}
    assert sticky_uplinks(config) == {"tor": Uplink(0x160, 7860, "10.77.0.60")}
    ruleset = router_ruleset(config)
    assert ruleset is not None and "ip daddr @smart_tor_sticky meta mark set 0x160" in ruleset


def test_direct_has_no_exit_to_keep() -> None:
    with pytest.raises(ValidationError, match="direct has no exit to keep"):
        smart_box({"domain": "claude.ai", "via": "direct", "sticky": True})


def test_sticky_is_a_rule_of_smart_only() -> None:
    assert sticky_uplinks(smart_box(CLAUDE, mode="full", default_upstream="tor")) == {}


def test_the_sticky_table_keeps_its_kill_switch_even_with_failopen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Direct would change the address just as a fallback does: the table holds its traffic."""
    calls = fake_host(monkeypatch)
    apply_router(smart_box(CLAUDE, failopen=True))
    steps = [" ".join(argv) for argv in calls]
    assert "ip route replace unreachable default metric 4294967295 table 7860" in steps
    assert "ip route del unreachable default metric 4294967295 table 7760" in steps
    assert "ip rule add fwmark 0x160 table 7860 priority 7860" in steps


def test_every_sticky_slot_is_cleaned_up_by_number() -> None:
    for uplink in (VPS, TOR):
        assert sticky_slot(uplink) in ALL_SLOTS


class Host:
    def __init__(self) -> None:
        self.tables: dict[int, str | None] = {}

    def route(self, uplink: Uplink, via: Uplink | None) -> None:
        self.tables[uplink.table] = None if via is None else via.gateway


def test_a_silent_uplink_moves_its_table_but_holds_its_sticky_one() -> None:
    host = Host()
    plan = ExitPlan(
        uplinks={"tor": TOR, "vps": VPS},
        routed=("tor",),
        fallback=("vps",),
        sticky={"tor": sticky_slot(TOR)},
    )
    watchers = UplinkWatchers(plan, route=host.route)
    watchers.settle("vps", True)
    watchers.settle("tor", True)
    assert host.tables == {7760: "10.77.0.60", 7860: "10.77.0.60"}
    watchers.settle("tor", False)
    assert host.tables == {7760: "10.77.0.10", 7860: None}
    watchers.settle("tor", True)
    assert host.tables == {7760: "10.77.0.60", 7860: "10.77.0.60"}


def test_the_plan_carries_the_sticky_slots() -> None:
    config = smart_box(CLAUDE)
    assert exit_plan(config, ["tor"]).sticky == {"tor": sticky_slot(TOR)}


def test_the_bot_under_a_sticky_rule_takes_the_sticky_mark() -> None:
    config = smart_box(CLAUDE)
    found = exit_for(config, "smart_tor_sticky", IPv4Address("160.79.104.10"))
    assert found is not None and (found.key, found.mark) == ("tor", 0x160)


def test_a_sticky_rule_is_written_and_read_back(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(render_config(smart_box()), encoding="utf-8")
    config = smart_box(CLAUDE)
    assert config.routing is not None
    set_domain_rule(path, config.routing.domains[0])
    assert "      sticky: true\n" in path.read_text(encoding="utf-8")
    routing = load_config(path).routing
    assert routing is not None and routing.domains[0].sticky
    # the template writes it the same way
    assert "      sticky: true\n" in render_config(config)
