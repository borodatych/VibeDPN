"""routing.fallback (decision 32): the traffic of a silent uplink goes through the first one that
answers — the chain, the routes of the tables, the watchers, the status and the doctor."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from vibedpn import event_view
from vibedpn.api.app import create_app
from vibedpn.api.models import EventView
from vibedpn.api.state import BoxState
from vibedpn.api.uplink import UplinkState, UplinkWatchers
from vibedpn.bootstrap import render_config
from vibedpn.config import Config, Upstream, load_config
from vibedpn.doctor import CheckResult, DoctorFacts, evaluate
from vibedpn.engine import router
from vibedpn.engine.events import Event, EventAction
from vibedpn.engine.router import (
    UPLINKS,
    ExitPlan,
    RoutingFacts,
    Uplink,
    exit_plan,
    exit_routes,
    read_routing,
    set_exit_route,
    wg_uplinks,
)

from .conftest import client_config

VPS, TOR, XRAY = UPLINKS[Upstream.VPS], UPLINKS[Upstream.TOR], UPLINKS[Upstream.XRAY]


def chained(fallback: list[str], **routing: object) -> dict[str, Any]:
    """A box with a LAN in full through vps, with tor and a second VPS as named exit `second`."""
    raw = client_config()
    raw["upstreams"] = {
        "vps": {"enabled": True},
        "tor": {"enabled": True},
        "wg": {"second": {"enabled": True}},
    }
    raw["routing"] = {"mode": "full", "default_upstream": "vps", "fallback": fallback, **routing}
    return raw


# --- the chain in config.yaml ---


def test_the_chain_names_enabled_uplinks_once_each() -> None:
    config = Config.model_validate(chained(["wg-second", "tor"]))
    assert config.routing is not None and config.routing.fallback == ["wg-second", "tor"]
    for bad, message in [
        (["tor", "tor"], "names an uplink twice: tor"),
        (["warp"], "'warp' is not an uplink"),
        (["dpn-de"], "'dpn-de' is not an uplink"),  # a rule country serves its rules only
        (["wg-Second"], "names no usable uplink"),
        (["dpn"], "routing.fallback: 'dpn' is not an enabled uplink"),
        (["wg-third"], "routing.fallback: 'wg-third' is not an enabled uplink"),
    ]:
        with pytest.raises(ValidationError, match=message):
            Config.model_validate(chained(bad))


# --- which gateway carries a table ---


def test_a_silent_uplink_goes_through_the_first_answering_one_of_the_chain() -> None:
    chain = ["wg-second", "tor"]
    assert exit_routes(["vps"], chain, {"vps": True, "tor": True}) == {"vps": "vps"}
    assert exit_routes(["vps"], chain, {"vps": False, "wg-second": False, "tor": True}) == {
        "vps": "tor"
    }
    assert exit_routes(["vps"], chain, {"vps": False, "wg-second": True, "tor": True}) == {
        "vps": "wg-second"
    }
    assert exit_routes(["vps"], chain, {"vps": False, "tor": False}) == {"vps": None}
    # not probed yet: the table stays as it is; a fallback not probed yet is no exit
    assert exit_routes(["vps"], chain, {"tor": True}) == {}
    assert exit_routes(["vps"], chain, {"vps": False, "wg-second": True}) == {"vps": "wg-second"}


def test_an_uplink_of_the_chain_never_falls_back_to_itself() -> None:
    """A rule through tor with tor in the chain: its traffic goes on to the next one."""
    alive = {"vps": True, "tor": False}
    assert exit_routes(["vps", "tor"], ["tor", "vps"], alive) == {"vps": "vps", "tor": "vps"}


def test_the_plan_watches_the_chain_and_routes_only_the_uplinks_in_use() -> None:
    config = Config.model_validate(chained(["wg-second", "tor"], failopen=True))
    plan = exit_plan(config, ["vps"])
    second = wg_uplinks(config)["second"]
    assert plan.uplinks == {"vps": VPS, "wg-second": second, "tor": TOR}
    assert plan.routed == ("vps",)
    assert plan.fallback == ("wg-second", "tor")
    assert plan.failopen
    # an uplink both in use and in the chain is watched once
    assert list(exit_plan(config, ["vps", "tor"]).uplinks) == ["vps", "tor", "wg-second"]


# --- the routes on the host ---


def fake_ip(monkeypatch: pytest.MonkeyPatch, listing: list[dict[str, Any]]) -> list[str]:
    calls: list[str] = []

    def run(argv: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(" ".join(argv))
        if argv[:4] == ["ip", "-j", "route", "show"]:
            return SimpleNamespace(returncode=0, stdout=json.dumps(listing), stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(router, "find_ip", lambda: "ip")
    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_a_table_moves_to_another_gateway_in_one_step(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = fake_ip(monkeypatch, [])
    set_exit_route(VPS, TOR)
    assert calls == ["ip route replace default via 10.77.0.60 dev vibedpn0 table 7710"]


def test_a_withdrawal_removes_the_gateway_route_whichever_it_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A route through a fallback left behind would carry the traffic on after the chain moved;
    the kill switch has no gateway and stays."""
    listing: list[dict[str, Any]] = [
        {"dst": "default", "gateway": "10.77.0.60", "dev": "vibedpn0", "flags": []},
        {"type": "unreachable", "dst": "default", "metric": 4294967295, "flags": []},
    ]
    calls = fake_ip(monkeypatch, listing)
    set_exit_route(VPS, None)
    assert calls == [
        "ip -j route show table 7710",
        "ip route del default via 10.77.0.60 dev vibedpn0 table 7710",
    ]


def test_the_host_facts_name_the_uplink_a_table_points_at(monkeypatch: pytest.MonkeyPatch) -> None:
    config = Config.model_validate(chained(["tor"]))
    rules = [{"priority": 7710, "src": "all", "fwmark": "0x10", "table": "7710"}]
    tables = {
        "7710": [
            {"dst": "default", "gateway": "10.77.0.60", "dev": "vibedpn0"},
            {"type": "unreachable", "dst": "default", "metric": 4294967295},
        ]
    }

    def run(argv: list[str], **_kwargs: object) -> SimpleNamespace:
        if argv[1:3] == ["-j", "rule"]:
            return SimpleNamespace(returncode=0, stdout=json.dumps(rules), stderr="")
        return SimpleNamespace(returncode=0, stdout=json.dumps(tables.get(argv[-1], [])), stderr="")

    monkeypatch.setattr(router, "find_ip", lambda: "ip")
    monkeypatch.setattr(subprocess, "run", run)
    facts = read_routing(config)
    assert facts.gateway_routes == {"vps": False}  # not its own gateway
    assert facts.last_resort_routes == {"vps": True}
    assert facts.exits == {"vps": "tor"}


# --- the watchers ---


class Host:
    """The routes the watchers set, by table."""

    def __init__(self) -> None:
        self.tables: dict[int, str | None] = {}
        self.calls = 0

    def route(self, uplink: Uplink, via: Uplink | None) -> None:
        self.calls += 1
        self.tables[uplink.table] = None if via is None else via.gateway


def watchers_for(
    fallback: tuple[str, ...], *, failopen: bool = False
) -> tuple[UplinkWatchers, Host, list[Event], list[tuple[str, str | None, str | None]]]:
    host = Host()
    journal: list[Event] = []
    moves: list[tuple[str, str | None, str | None]] = []
    plan = ExitPlan(
        uplinks={"vps": VPS, "tor": TOR, "xray": XRAY},
        routed=("vps",),
        fallback=fallback,
        failopen=failopen,
    )
    watchers = UplinkWatchers(
        plan,
        journal=journal.append,
        reroute=lambda key, before, now: moves.append((key, before, now)),
        route=host.route,
    )
    return watchers, host, journal, moves


def test_the_watchers_move_a_silent_table_along_the_chain_and_back() -> None:
    watchers, host, journal, moves = watchers_for(("tor", "xray"))
    watchers.settle("vps", True)
    assert host.tables == {7710: "10.77.0.10"} and moves == [] and journal == []
    watchers.settle("tor", False)
    watchers.settle("xray", True)
    watchers.settle("vps", False)
    assert host.tables == {7710: "10.77.0.70"}
    watchers.settle("tor", True)  # an earlier uplink of the chain answers again: it takes over
    assert host.tables == {7710: "10.77.0.60"}
    watchers.settle("vps", True)
    assert host.tables == {7710: "10.77.0.10"}
    assert moves == [("vps", "vps", "xray"), ("vps", "xray", "tor"), ("vps", "tor", "vps")]
    assert [(item.subject, item.action, item.detail) for item in journal] == [
        ("vps", EventAction.REROUTED, {"through": "xray"}),
        ("vps", EventAction.REROUTED, {"through": "tor"}),
        ("vps", EventAction.REROUTED, {"through": "vps"}),
    ]
    # the tables of the chain carry no LAN traffic: the watchers never route them
    assert set(host.tables) == {7710}


def test_an_empty_chain_leaves_the_kill_switch_and_journals_nothing_new() -> None:
    watchers, host, journal, moves = watchers_for(())
    watchers.settle("vps", True)
    watchers.settle("vps", False)
    assert host.tables == {7710: None}
    assert moves == [("vps", "vps", None)]
    assert journal == []  # the gateway events of the watcher tell this already


def test_a_chain_that_runs_dry_says_where_the_traffic_goes() -> None:
    watchers, _host, journal, _moves = watchers_for(("tor",), failopen=True)
    watchers.settle("tor", True)
    watchers.settle("vps", False)
    watchers.settle("tor", False)
    assert [item.detail for item in journal] == [{"through": "tor"}, {"through": "direct"}]


def test_the_own_table_is_routed_on_every_round_and_the_others_only_when_they_move() -> None:
    watchers, host, _journal, _moves = watchers_for(("tor",))
    watchers.settle("vps", True)
    watchers.settle("vps", True)
    assert host.calls == 2  # a route removed behind the watchers' back comes back
    watchers.settle("tor", True)
    watchers.settle("tor", True)
    assert host.calls == 2  # tor answering changes nothing for vps


def test_a_round_of_an_uplink_the_plan_dropped_changes_nothing() -> None:
    watchers, host, _journal, _moves = watchers_for(("tor",))
    watchers.settle("dpn", False)
    assert host.calls == 0


def test_a_new_chain_moves_the_tables_at_once() -> None:
    """The owner adds a fallback while vps is silent: its table moves without waiting a round."""
    watchers, host, _journal, _moves = watchers_for(())

    async def watch(_key: str, _uplink: Uplink, _report: object) -> None:
        await asyncio.Event().wait()

    watchers._watch = watch  # the rounds come from the test, not from probes

    async def scenario() -> None:
        runner = asyncio.ensure_future(watchers.run())
        await asyncio.sleep(0.01)
        watchers.settle("tor", True)
        watchers.settle("vps", False)
        assert host.tables == {7710: None}
        watchers.sync(ExitPlan({"vps": VPS, "tor": TOR}, ("vps",), ("tor",)))
        await asyncio.sleep(0.05)
        assert host.tables == {7710: "10.77.0.60"}
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)

    asyncio.run(scenario())


# --- status, routing API and doctor ---


class FakeWatchers:
    def __init__(self) -> None:
        self.synced: list[ExitPlan] = []

    def sync(self, plan: ExitPlan) -> None:
        self.synced.append(plan)

    def states(self) -> dict[str, UplinkState]:
        return {
            "vps": UplinkState(False, 1_700_000_000.0),
            "tor": UplinkState(True, 1_700_000_000.0),
        }


def app_for(
    tmp_path: Path, raw: dict[str, Any], facts: RoutingFacts
) -> tuple[TestClient, Path, FakeWatchers]:
    path = tmp_path / "config.yaml"
    path.write_text(render_config(Config.model_validate(raw)), encoding="utf-8")
    config = load_config(path)
    watchers = FakeWatchers()
    state = BoxState(config, path, apply=lambda _config: ["vps"], watchers=watchers)  # type: ignore[arg-type]
    app = create_app(
        config,
        state=state,
        watchers=watchers,  # type: ignore[arg-type]
        routing_reader=lambda _config: facts,
        dns_mode=lambda _config, _changed: True,
        dns_reconnect=lambda _config: None,
    )
    return TestClient(app), path, watchers


def test_status_names_the_fallback_that_carries_the_lan(tmp_path: Path) -> None:
    facts = RoutingFacts(True, {"vps": False}, {"vps": True}, {"vps": "tor"})
    client, _path, _watchers = app_for(tmp_path, chained(["tor"]), facts)
    body = client.get("/status").json()
    assert body["fallback"] == ["tor"]
    assert body["lan_without_exit"] is False  # silent vps, but tor carries the LAN
    uplinks = {item["name"]: item for item in body["uplinks"]}
    assert uplinks["vps"]["exit_through"] == "tor" and not uplinks["vps"]["fallback"]
    assert uplinks["tor"]["fallback"] and not uplinks["tor"]["in_use"]
    assert uplinks["tor"]["gateway_alive"] is True
    held = RoutingFacts(True, {"vps": False}, {"vps": True}, {"vps": None})
    client, _path, _watchers = app_for(tmp_path, chained(["tor"]), held)
    assert client.get("/status").json()["lan_without_exit"] is True


def test_the_chain_changes_live_through_the_api(tmp_path: Path) -> None:
    facts = RoutingFacts(True, {"vps": True}, {"vps": True}, {"vps": "vps"})
    client, path, watchers = app_for(tmp_path, chained([]), facts)
    response = client.put("/routing", json={"fallback": ["wg-second", "tor"]})
    assert response.status_code == 200 and response.json()["fallback"] == ["wg-second", "tor"]
    routing = load_config(path).routing
    assert routing is not None and routing.fallback == ["wg-second", "tor"]
    assert watchers.synced[-1].fallback == ("wg-second", "tor")
    assert list(watchers.synced[-1].uplinks) == ["vps", "wg-second", "tor"]
    refused = client.put("/routing", json={"fallback": ["dpn"]})
    assert refused.status_code == 422 and "not an enabled uplink" in refused.json()["detail"]
    assert client.put("/routing", json={"fallback": []}).json()["fallback"] == []
    assert client.put("/routing", json={}).status_code == 422


def router_verdict(config: Config, **overrides: object) -> CheckResult:
    base: dict[str, object] = {
        "config": config,
        "config_error": "",
        "config_hint": "",
        "env_current": True,
        "secrets": {},
        "wireguard": True,
        "nf_tables": True,
        "ip_forward": True,
        "listeners": [],
        "is_root": True,
        "docker_error": "",
        "listeners_error": "",
        "services": [],
        "active_services": [],
        "firewall_table": None,
        "router_table": True,
        "router_rules": True,
        "router_docker_user": True,
        "uplink_routes": {"vps": True},
        "last_resort_routes": {"vps": True},
        "rp_filter": 2,
    }
    base.update(overrides)
    results = evaluate(DoctorFacts(**base))  # type: ignore[arg-type]
    return next(item for item in results if item.name == "router")


def test_doctor_tells_the_chain_and_the_fallback_that_carries_a_silent_uplink() -> None:
    config = Config.model_validate(chained(["wg-second", "tor"]))
    assert router_verdict(config).detail == (
        "routing.mode full, uplinks in use: vps (10.77.0.10); fallback: wg-second, tor"
    )
    moved = router_verdict(config, uplink_routes={"vps": False}, uplink_exits={"vps": "tor"})
    assert moved.detail == (
        "uplink vps gateway 10.77.0.10 does not answer; its traffic goes through tor"
        " (routing.fallback)"
    )


def test_the_journal_says_where_the_traffic_went() -> None:
    def text(through: str) -> str:
        view = EventView(
            time=0.0,
            kind="uplink",
            subject="vps",
            name=None,
            action="rerouted",
            detail={"through": through},
        )
        return event_view.event_text(view)

    assert text("tor") == "its traffic goes through tor"
    assert text("direct") == "its traffic goes direct"
    assert text("held") == "its traffic is held (kill switch)"
