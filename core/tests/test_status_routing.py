"""The status screen's API: /status, PUT /routing, watcher state, core's AdGuard user."""

import asyncio
import base64
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from vibedpn.api import client as core_api
from vibedpn.api.app import create_app
from vibedpn.api.state import BoxState
from vibedpn.api.uplink import UplinkState, UplinkWatchers, watch_uplink
from vibedpn.bootstrap import render_config
from vibedpn.config import Config, RoutingMode, Upstream, load_config
from vibedpn.engine.adguard import CORE_USER, AdguardError, adguard_text, set_aaaa_disabled
from vibedpn.engine.router import RouterError, RoutingFacts

from .conftest import client_config, vps_config

HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
FACTS = RoutingFacts(True, {"vps": True}, {"vps": True})


class FakeWatchers:
    def __init__(self, states: dict[Upstream, UplinkState]) -> None:
        self._states = states
        self.synced: list[list[Upstream]] = []

    def sync(self, uplinks: list[Upstream]) -> None:
        self.synced.append(list(uplinks))

    def states(self) -> dict[Upstream, UplinkState]:
        return dict(self._states)


def box(
    tmp_path: Path,
    raw: dict[str, object] | None = None,
    *,
    alive: bool | None = True,
    apply: object = None,
    dns: object = None,
) -> tuple[TestClient, Path]:
    path = tmp_path / "config.yaml"
    path.write_text(render_config(Config.model_validate(raw or client_config())), encoding="utf-8")
    config = load_config(path)
    states = {} if alive is None else {Upstream.VPS: UplinkState(alive, 1_700_000_000.0)}
    watchers = FakeWatchers(states)
    state = BoxState(
        config,
        path,
        apply=apply or (lambda _config: [Upstream.VPS]),  # type: ignore[arg-type]
        watchers=watchers,  # type: ignore[arg-type]
    )
    app = create_app(
        config,
        state=state,
        watchers=watchers,  # type: ignore[arg-type]
        routing_reader=lambda _config: FACTS,
        dns_mode=dns or (lambda _config: True),  # type: ignore[arg-type]
    )
    return TestClient(app), path


def test_status_tells_when_the_kill_switch_holds_the_lan(tmp_path: Path) -> None:
    client, _ = box(tmp_path, alive=False)
    body = client.get("/status").json()
    assert body["mode"] == "full" and body["default_upstream"] == "vps"
    assert body["lan_without_exit"] is True and body["rules_current"] is True
    vps = next(item for item in body["uplinks"] if item["name"] == "vps")
    assert vps["enabled"] and vps["in_use"] and vps["gateway_alive"] is False
    assert vps["gateway_route"] is True and vps["kill_switch_route"] is True
    assert vps["checked_at"].startswith("2023-11-14")
    dpn = next(item for item in body["uplinks"] if item["name"] == "dpn")
    assert dpn["enabled"] is False and dpn["gateway_alive"] is None


def test_an_answering_gateway_or_failopen_keeps_the_exit(tmp_path: Path) -> None:
    client, _ = box(tmp_path, alive=True)
    assert client.get("/status").json()["lan_without_exit"] is False
    raw = client_config()
    raw["routing"] = {"mode": "full", "default_upstream": "vps", "failopen": True}
    client, _ = box(tmp_path, raw, alive=False)
    assert client.get("/status").json()["lan_without_exit"] is False
    client, _ = box(tmp_path, alive=None)  # not probed yet: no verdict of silence
    assert client.get("/status").json()["lan_without_exit"] is False


def test_a_box_without_a_lan_has_no_status(tmp_path: Path) -> None:
    client, _ = box(tmp_path, vps_config())
    assert client.get("/status").status_code == 404
    assert client.put("/routing", json={"mode": "off"}).status_code == 404


def test_routing_changes_live_and_reports_adguard(tmp_path: Path) -> None:
    told: list[RoutingMode] = []

    def dns(config: Config) -> bool:
        assert config.routing is not None
        told.append(config.routing.mode)
        return True

    client, path = box(tmp_path, dns=dns)
    response = client.put("/routing", json={"mode": "off"})
    assert response.status_code == 200, response.text
    assert response.json() == {"mode": "off", "default_upstream": "vps", "adguard": "applied"}
    routing = load_config(path).routing
    assert routing is not None and routing.mode is RoutingMode.OFF
    assert told == [RoutingMode.OFF]
    assert client.get("/status").json()["mode"] == "off"


def test_a_silent_or_absent_adguard_does_not_undo_the_router(tmp_path: Path) -> None:
    def silent(_config: Config) -> bool:
        raise AdguardError("AdGuard does not answer")

    client, path = box(tmp_path, dns=silent)
    assert client.put("/routing", json={"mode": "off"}).json()["adguard"] == "pending"
    routing = load_config(path).routing
    assert routing is not None and routing.mode is RoutingMode.OFF
    client, _ = box(tmp_path, dns=lambda _config: None)
    assert client.put("/routing", json={"mode": "full"}).json()["adguard"] == "none"


def test_bad_routing_requests_change_nothing(tmp_path: Path) -> None:
    client, path = box(tmp_path)
    before = path.read_text(encoding="utf-8")
    assert client.put("/routing", json={}).status_code == 422
    assert client.put("/routing", json={"mode": "smart"}).status_code == 422
    refused = client.put("/routing", json={"default_upstream": "dpn"})  # dpn is not enabled
    assert refused.status_code == 422 and "not changed" in refused.json()["detail"]
    assert path.read_text(encoding="utf-8") == before


def test_a_refused_router_restores_the_mode(tmp_path: Path) -> None:
    def apply(config: Config) -> list[Upstream]:
        if config.routing is not None and config.routing.mode is RoutingMode.OFF:
            raise RouterError("nft -f - failed")
        return [Upstream.VPS]

    client, path = box(tmp_path, apply=apply)
    before = path.read_text(encoding="utf-8")
    response = client.put("/routing", json={"mode": "off"})
    assert response.status_code == 503 and "restored" in response.json()["detail"]
    assert path.read_text(encoding="utf-8") == before


def test_the_watcher_reports_every_round() -> None:
    reports: list[UplinkState] = []
    answers: list[bool | OSError] = [True, OSError(13, "Permission denied")]

    def probe(_gateway: str, _timeout: float) -> bool:
        answer = answers.pop(0)
        if isinstance(answer, OSError):
            raise answer
        return answer

    rounds = 0

    async def sleep(_seconds: float) -> None:
        nonlocal rounds
        rounds += 1
        if rounds == 2:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            watch_uplink(
                Upstream.VPS,
                probe=probe,
                apply=lambda _upstream, _alive: None,
                sleep=sleep,
                report=reports.append,
            )
        )
    assert [item.alive for item in reports] == [True, False]
    assert reports[0].error == "" and "Permission denied" in reports[1].error


def test_watchers_keep_the_state_of_the_uplinks_in_use() -> None:
    async def watch(upstream: Upstream, report: object) -> None:
        assert callable(report)
        report(UplinkState(upstream is Upstream.VPS, 1.0))
        await asyncio.Event().wait()

    async def scenario() -> None:
        watchers = UplinkWatchers([Upstream.VPS, Upstream.DPN], watch=watch)
        runner = asyncio.ensure_future(watchers.run())
        await asyncio.sleep(0.01)
        assert {k: v.alive for k, v in watchers.states().items()} == {
            Upstream.VPS: True,
            Upstream.DPN: False,
        }
        watchers.sync([Upstream.VPS])
        await asyncio.sleep(0.01)
        assert list(watchers.states()) == [Upstream.VPS]
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)

    asyncio.run(scenario())


def test_core_gets_its_own_adguard_user_once() -> None:
    raw = client_config()
    config = Config.model_validate(raw)
    first = adguard_text(None, config, HASH, core_password="core-secret-123")
    second = adguard_text(first, config, HASH, core_password="core-secret-123")
    assert second == first  # the same password keeps the stored hash: no rewrite per start
    third = adguard_text(first, config, HASH, core_password="another-secret-1")
    assert third != first and "vibedpn-core" in third


def test_the_dns_mode_reaches_adguard_with_basic_auth(tmp_path: Path) -> None:
    (tmp_path / "adguard-core-password").write_text("core-secret-123\n", encoding="utf-8")
    seen: list[httpx.Request] = []

    def adguard(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    config = Config.model_validate(client_config())  # mode full
    assert set_aaaa_disabled(config, tmp_path, transport=httpx.MockTransport(adguard)) is True
    request = seen[0]
    assert str(request.url) == "http://192.168.1.50:3000/control/dns_config"
    assert json.loads(request.content) == {"disable_ipv6": True}
    token = base64.b64encode(f"{CORE_USER}:core-secret-123".encode()).decode()
    assert request.headers["authorization"] == f"Basic {token}"
    refused = httpx.MockTransport(lambda _request: httpx.Response(401))
    with pytest.raises(AdguardError, match="HTTP 401"):
        set_aaaa_disabled(config, tmp_path, transport=refused)
    raw = client_config()
    raw["dns"] = {"enabled": False}
    assert set_aaaa_disabled(Config.model_validate(raw), tmp_path) is None


def test_client_reads_status_and_sets_routing() -> None:
    status = {
        "mode": "full",
        "default_upstream": "vps",
        "failopen": False,
        "rules_current": True,
        "lan_without_exit": True,
        "uplinks": [],
    }

    def core(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=status)
        assert json.loads(request.content) == {"mode": "off"}
        return httpx.Response(
            200, json={"mode": "off", "default_upstream": "vps", "adguard": "none"}
        )

    transport = httpx.MockTransport(core)
    assert core_api.fetch_status(4480, transport=transport).lan_without_exit is True
    view = core_api.set_routing(4480, RoutingMode.OFF, transport=transport)
    assert view.adguard == "none"
    failing = httpx.MockTransport(lambda _request: httpx.Response(404, json={"detail": "no LAN"}))
    with pytest.raises(core_api.RoutingRequestError, match="no LAN"):
        core_api.fetch_status(4480, transport=failing)
