"""routing.failopen applied live: the routing API writes it, the watchers take the new plan, and a
table without exit tells its new path, so AdGuard leaves the connections of the old one."""

from __future__ import annotations

import asyncio
from pathlib import Path

from vibedpn.api.app import reconnect_on_reroute
from vibedpn.config import Config, load_config
from vibedpn.engine.router import ExitPlan, RoutingFacts

from .test_fallback import TOR, VPS, app_for, chained, watchers_for


def test_failopen_changes_live_through_the_api(tmp_path: Path) -> None:
    facts = RoutingFacts(True, {"vps": False}, {"vps": True}, {"vps": None})
    client, path, watchers = app_for(tmp_path, chained([]), facts)
    response = client.put("/routing", json={"failopen": True})
    assert response.status_code == 200 and response.json()["failopen"] is True
    routing = load_config(path).routing
    assert routing is not None and routing.failopen
    assert client.get("/status").json()["lan_without_exit"] is False  # it goes direct now
    response = client.put("/routing", json={"failopen": False})
    assert response.status_code == 200 and response.json()["failopen"] is False
    assert [plan.failopen for plan in watchers.synced] == [True, False]
    assert client.get("/status").json()["lan_without_exit"] is True
    empty = client.put("/routing", json={})
    assert empty.status_code == 422 and "failopen" in empty.json()["detail"]


def test_a_turn_of_failopen_moves_a_table_without_exit_only() -> None:
    watchers, host, journal, moves = watchers_for(())

    async def watch(_key: str, _uplink: object, _report: object) -> None:
        await asyncio.Event().wait()

    watchers._watch = watch  # the rounds come from the test, not from probes

    def plan(*, failopen: bool) -> ExitPlan:
        return ExitPlan({"vps": VPS, "tor": TOR}, ("vps",), (), failopen=failopen)

    async def turn(failopen: bool) -> None:
        watchers.sync(plan(failopen=failopen))
        await asyncio.sleep(0.05)

    async def scenario() -> None:
        runner = asyncio.ensure_future(watchers.run())
        await asyncio.sleep(0.01)
        watchers.settle("vps", False)
        assert moves == [("vps", "vps", None)]
        await turn(True)  # held → direct: the same table, a new path
        await turn(True)  # no turn, no move
        await turn(False)  # direct → held
        assert moves == [("vps", "vps", None), ("vps", None, None), ("vps", None, None)]
        watchers.settle("vps", True)
        moves.clear()
        await turn(True)  # the gateway answers: the turn moves nothing
        assert moves == []
        assert host.tables == {VPS.table: VPS.gateway}
        assert journal == []  # the gateway events and the edit itself tell it
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)

    asyncio.run(scenario())


def test_adguard_leaves_the_held_path_when_failopen_turns_on() -> None:
    raw = chained([])
    config = Config.model_validate(raw)
    reconnected: list[Config] = []
    follow = reconnect_on_reroute(lambda: config, reconnected.append)
    follow("vps", "vps", None)  # the gateway falls silent: its queries are held
    assert reconnected == []
    raw["routing"]["failopen"] = True
    config = Config.model_validate(raw)
    follow("vps", None, None)  # failopen on: the held queries go direct
    assert len(reconnected) == 1
    raw["routing"]["failopen"] = False
    config = Config.model_validate(raw)
    follow("vps", None, None)  # off again: held, nothing to close
    follow("vps", None, "vps")  # the gateway answers: the direct connections are dead
    assert len(reconnected) == 2
