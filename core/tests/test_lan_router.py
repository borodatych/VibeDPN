"""LAN router: rendering per routing.mode, ip rule planning, DOCKER-USER groups, apply order."""

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from ruamel.yaml import YAML

from vibedpn.config import Config, Upstream
from vibedpn.engine import router
from vibedpn.engine.router import (
    EGRESS_COMMENT,
    ROUTER_COMMENT,
    UPLINKS,
    UPSTREAMS_BRIDGE,
    UPSTREAMS_SUBNET,
    RouterError,
    active_uplink,
    apply_router,
    plan_docker_user,
    plan_rules,
    remove_router,
    router_docker_user_rules,
    router_ruleset,
    set_gateway_route,
)

COMPOSE = Path(__file__).resolve().parents[2] / "compose.yaml"
# `ip -j rule show` on iproute2 of alpine 3.24 with the vps rule in place (2026-09-13).
RULES_WITH_VPS = (
    '[{"priority":0,"src":"all","table":"local"},'
    '{"priority":7710,"src":"all","fwmark":"0x10","table":"7710"},'
    '{"priority":32766,"src":"all","table":"main"},'
    '{"priority":32767,"src":"all","table":"default"}]'
)
RULES_EMPTY = (
    '[{"priority":0,"src":"all","table":"local"},'
    '{"priority":32766,"src":"all","table":"main"},'
    '{"priority":32767,"src":"all","table":"default"}]'
)


def lan_box(mode: str = "full", upstream: str = "vps", *, failopen: bool = False) -> Config:
    raw: dict[str, Any] = {
        "version": 1,
        "role": "client" if upstream == "vps" else "home",
        "network": {
            "lan_interface": "eth0",
            "lan_subnet": "192.168.1.0/24",
            "lan_address": "192.168.1.50",
        },
        "routing": {"mode": mode, "default_upstream": upstream, "failopen": failopen},
        "upstreams": {upstream: {"enabled": True}},
    }
    if upstream == "dpn":
        raw["provider"] = {"enabled": True}
    return Config.model_validate(raw)


def vps_box() -> Config:
    return Config.model_validate(
        {
            "version": 1,
            "role": "vps",
            "provider": {"enabled": True},
            "wg_server": {"endpoint": "203.0.113.7"},
        }
    )


def test_uplinks_match_compose() -> None:
    """Gateway addresses and the bridge name live in compose.yaml; the router must agree."""
    compose = YAML(typ="safe").load(COMPOSE.read_text(encoding="utf-8"))
    services = compose["services"]
    assert services["wg-client"]["networks"]["upstreams"]["ipv4_address"] == (
        UPLINKS[Upstream.VPS].gateway
    )
    assert services["myst-consumer"]["networks"]["upstreams"]["ipv4_address"] == (
        UPLINKS[Upstream.DPN].gateway
    )
    network = compose["networks"]["upstreams"]
    assert network["driver_opts"]["com.docker.network.bridge.name"] == UPSTREAMS_BRIDGE
    assert network["ipam"]["config"][0]["subnet"] == UPSTREAMS_SUBNET


def test_mode_full_marks_lan_traffic_for_its_uplink() -> None:
    text = router_ruleset(lan_box())
    assert text is not None
    assert (
        'iifname "eth0" ip saddr 192.168.1.0/24 ip daddr != { 192.168.1.0/24, 10.77.0.0/24 }'
        " fib daddr type != local meta mark set 0x10"
    ) in text
    assert "meta mark set 0x20" in (router_ruleset(lan_box(upstream="dpn")) or "")


def test_mode_off_marks_nothing_but_still_routes_direct() -> None:
    text = router_ruleset(lan_box("off"))
    assert text is not None
    assert "meta mark set" not in text
    assert 'iifname "eth0" oifname "eth0" ip saddr 192.168.1.0/24 masquerade' in text
    assert 'iifname "eth0" ip daddr 10.77.0.0/24 drop' in text
    assert 'oifname "eth0" icmp type redirect drop' in text
    assert 'iifname "eth0" meta nfproto ipv6 drop' in text
    assert active_uplink(lan_box("off")) is None


def test_no_router_without_a_lan_and_no_smart_mode_yet() -> None:
    assert router_ruleset(vps_box()) is None
    assert router_docker_user_rules(vps_box()) == []
    with pytest.raises(RouterError, match="smart"):
        router_ruleset(lan_box("smart"))


def test_rule_plan_from_a_real_listing() -> None:
    vps_rule = ["priority", "7710", "fwmark", "0x10", "table", "7710"]
    assert plan_rules(RULES_WITH_VPS, Upstream.VPS) == ([], [])
    assert plan_rules(RULES_EMPTY, Upstream.VPS) == ([], [Upstream.VPS])
    assert plan_rules(RULES_WITH_VPS, None) == ([vps_rule], [])
    assert plan_rules(RULES_WITH_VPS, Upstream.DPN) == ([vps_rule], [Upstream.DPN])
    # A foreign rule at our priority goes by its own selector; the exact one of ours stays.
    foreign = RULES_WITH_VPS.replace(
        '{"priority":32766', '{"priority":7710,"src":"all","table":"main"},{"priority":32766'
    )
    assert plan_rules(foreign, Upstream.VPS) == ([["priority", "7710", "table", "main"]], [])
    doubled = RULES_WITH_VPS.replace(
        '{"priority":32766',
        '{"priority":7710,"src":"all","fwmark":"0x10","table":"7710"},{"priority":32766',
    )
    assert plan_rules(doubled, Upstream.VPS) == ([vps_rule], [])


def as_listing(*groups: list[list[str]]) -> str:
    lines = ["-N DOCKER-USER"]
    for rules in groups:
        lines += ["-A DOCKER-USER " + " ".join(rule) for rule in rules]
    return "\n".join(lines) + "\n"


def test_two_groups_share_the_top_of_docker_user() -> None:
    lan = router_docker_user_rules(lan_box())
    egress = [
        ["-s", "10.78.0.0/24", "-i", "wg0", "!", "-o", "wg0", "-m", "comment", "--comment",
         EGRESS_COMMENT, "-j", "ACCEPT"],
    ]  # fmt: skip
    listing = as_listing(egress, lan)
    assert plan_docker_user(listing, lan, ROUTER_COMMENT) == ([], [])
    assert plan_docker_user(listing, egress, EGRESS_COMMENT) == ([], [])
    shadowed = as_listing([["-j", "RETURN"]], lan)
    delete, insert = plan_docker_user(shadowed, lan, ROUTER_COMMENT)
    assert len(delete) == 5 and insert == lan


def fake_host(monkeypatch: pytest.MonkeyPatch, rules: str = RULES_EMPTY) -> list[list[str]]:
    calls: list[list[str]] = []

    def run(argv: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(argv)
        if argv[:3] == ["ip", "-j", "rule"]:
            return SimpleNamespace(returncode=0, stdout=rules, stderr="")
        if argv[:2] == ["ip", "route"] and argv[2] in {"flush", "del"}:
            return SimpleNamespace(
                returncode=2, stdout="", stderr="Error: ipv4: FIB table does not exist."
            )
        if argv[0] == "iptables-nft" and "-S" in argv:
            return SimpleNamespace(returncode=0, stdout="-N DOCKER-USER\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(router, "find_nft", lambda: "nft")
    monkeypatch.setattr(router, "find_ip", lambda: "ip")
    monkeypatch.setattr(router, "find_iptables", lambda: ["iptables-nft"])
    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_apply_puts_the_kill_switch_before_any_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = fake_host(monkeypatch)
    assert apply_router(lan_box()) is Upstream.VPS
    steps = [" ".join(argv) for argv in calls]
    unreachable = steps.index("ip route replace unreachable default metric 4294967295 table 7710")
    rule = steps.index("ip rule add fwmark 0x10 table 7710 priority 7710")
    marks = steps.index("nft -f -")
    assert steps[0] == "nft -c -f -"
    assert unreachable < rule < marks
    assert "ip route flush table 7720" in steps  # the inactive uplink keeps no routes
    inserts = [step for step in steps if " -I DOCKER-USER 1 " in step]
    assert len(inserts) == 5
    # Inserted bottom-up at position 1: the replies are accepted before the DROP of new calls.
    assert inserts.index(next(s for s in inserts if s.endswith("-j DROP"))) < inserts.index(
        next(s for s in inserts if "RELATED,ESTABLISHED" in s and "-i vibedpn0" in s)
    )


def test_switching_uplinks_never_leaves_a_mark_without_its_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = fake_host(monkeypatch, RULES_WITH_VPS)
    assert apply_router(lan_box(upstream="dpn")) is Upstream.DPN
    steps = [" ".join(argv) for argv in calls]
    added = steps.index("ip rule add fwmark 0x20 table 7720 priority 7720")
    marks = steps.index("nft -f -")
    removed = steps.index("ip rule del priority 7710 fwmark 0x10 table 7710")
    assert added < marks < removed


def test_failopen_leaves_no_last_resort_route(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = fake_host(monkeypatch)
    apply_router(lan_box(failopen=True))
    steps = [" ".join(argv) for argv in calls]
    assert "ip route del unreachable default metric 4294967295 table 7710" in steps
    assert not any("route replace unreachable" in step for step in steps)


def test_mode_off_and_a_vps_remove_every_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = fake_host(monkeypatch, RULES_WITH_VPS)
    assert apply_router(lan_box("off")) is None
    steps = [" ".join(argv) for argv in calls]
    assert "ip rule del priority 7710 fwmark 0x10 table 7710" in steps
    assert not any("rule add" in step for step in steps)
    calls = fake_host(monkeypatch, RULES_WITH_VPS)
    remove_router()
    steps = [" ".join(argv) for argv in calls]
    assert steps[0] == "nft -f -"
    assert "ip rule del priority 7710 fwmark 0x10 table 7710" in steps
    assert {"ip route flush table 7710", "ip route flush table 7720"} <= set(steps)


def test_gateway_route_follows_the_watcher(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = fake_host(monkeypatch)
    set_gateway_route(Upstream.VPS, alive=True)
    set_gateway_route(Upstream.VPS, alive=False)  # missing already: not an error
    assert [" ".join(argv) for argv in calls] == [
        "ip route replace default via 10.77.0.10 dev vibedpn0 table 7710",
        "ip route del default via 10.77.0.10 dev vibedpn0 table 7710",
    ]
