"""The status screen's API: /status, PUT /routing, watcher state, core's AdGuard user."""

import asyncio
import base64
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from vibedpn.api import client as core_api
from vibedpn.api.app import create_app, reconnect_dns, reconnect_on_failover
from vibedpn.api.consumer import ConsumerStatus
from vibedpn.api.state import BoxState
from vibedpn.api.uplink import UplinkState, UplinkWatchers, watch_uplink
from vibedpn.bootstrap import render_config
from vibedpn.config import Config, RoutingMode, Upstream, load_config
from vibedpn.engine.adguard import CORE_USER, AdguardError, adguard_text, set_dns_mode
from vibedpn.engine.consumer import ConsumerState, CountryOffer
from vibedpn.engine.events import Event, EventAction, EventKind
from vibedpn.engine.myst import MystError
from vibedpn.engine.router import UPLINKS, RouterError, RoutingFacts, Uplink
from vibedpn.engine.sockdiag import SockDiagError

from .conftest import client_config, home_config, vps_config

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
    reconnect: object = None,
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
        dns_mode=dns or (lambda _config, _changed: True),  # type: ignore[arg-type]
        dns_reconnect=reconnect or (lambda _config: None),  # type: ignore[arg-type]
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

    def dns(config: Config, _changed: bool = False) -> bool:
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
    def silent(_config: Config, _changed: bool = False) -> bool:
        raise AdguardError("AdGuard does not answer")

    client, path = box(tmp_path, dns=silent)
    assert client.put("/routing", json={"mode": "off"}).json()["adguard"] == "pending"
    routing = load_config(path).routing
    assert routing is not None and routing.mode is RoutingMode.OFF
    client, _ = box(tmp_path, dns=lambda _config, _changed=False: None)
    assert client.put("/routing", json={"mode": "full"}).json()["adguard"] == "none"


def test_adguard_reconnects_when_the_uplink_of_its_queries_changes(tmp_path: Path) -> None:
    """Its connections opened along the old path would each fail the first query riding on them."""
    raw = client_config()
    raw["upstreams"] = {"vps": {"enabled": True}, "tor": {"enabled": True}}
    steps = [
        ({"mode": "off"}, True),  # full through vps -> direct
        ({"mode": "off"}, False),
        ({"mode": "smart"}, False),  # direct either way: the new upstreams restart AdGuard instead
        ({"mode": "full"}, True),
        ({"mode": "full"}, False),
        ({"default_upstream": "tor"}, True),
        ({"mode": "smart"}, True),
    ]
    reconnected: list[Config] = []
    client, _ = box(tmp_path, raw, reconnect=reconnected.append)
    for request, expected in steps:
        before = len(reconnected)
        assert client.put("/routing", json=request).status_code == 200
        assert (len(reconnected) > before) is expected, request
    routing = reconnected[-1].routing
    assert routing is not None and routing.mode is RoutingMode.SMART  # it gets the new config


def test_a_kernel_that_keeps_the_connections_leaves_the_switch_applied(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def refused(request: bytes) -> list[tuple[int, bytes]]:
        raise SockDiagError("the kernel cannot close sockets: it is built without it")

    reconnect_dns(Config.model_validate(client_config()), refused)
    assert "AdGuard keeps its upstream connections" in capsys.readouterr().err
    client, path = box(tmp_path, reconnect=lambda config: reconnect_dns(config, refused))
    assert client.put("/routing", json={"mode": "off"}).status_code == 200
    routing = load_config(path).routing
    assert routing is not None and routing.mode is RoutingMode.OFF


def test_failopen_reconnects_adguard_when_the_gateway_of_its_queries_changes_state() -> None:
    """With failopen a silent gateway sends its queries direct, an answering one takes them back."""
    raw = client_config()
    raw["routing"] = {"mode": "full", "default_upstream": "vps", "failopen": True}
    raw["upstreams"] = {"vps": {"enabled": True}, "tor": {"enabled": True}}
    config = Config.model_validate(raw)
    reconnected: list[Config] = []
    follow = reconnect_on_failover(lambda: config, reconnected.append)
    follow(Event(1.0, EventKind.UPLINK, "vps", EventAction.GATEWAY_SILENT))
    follow(Event(2.0, EventKind.UPLINK, "vps", EventAction.GATEWAY_ANSWERS))
    follow(Event(3.0, EventKind.UPLINK, "tor", EventAction.GATEWAY_SILENT))  # not its uplink
    follow(Event(4.0, EventKind.WIFI, "wlan0", EventAction.AP_DISABLED))
    assert len(reconnected) == 2
    raw["routing"]["failopen"] = False  # the kill switch: nothing moves, the path stays
    config = Config.model_validate(raw)
    follow(Event(5.0, EventKind.UPLINK, "vps", EventAction.GATEWAY_SILENT))
    assert len(reconnected) == 2


def hand_edit(path: Path, mode: str) -> None:
    """config.yaml changed by the owner in an editor, behind core's back."""
    config = load_config(path)
    routing = config.routing
    assert routing is not None
    edited = routing.model_copy(update={"mode": RoutingMode(mode)})
    path.write_text(render_config(config.model_copy(update={"routing": edited})), encoding="utf-8")


def test_core_rereads_a_hand_edit_and_applies_it_live(tmp_path: Path) -> None:
    """`vibedpn up` asks: the router, the watchers and AdGuard follow as after PUT /routing."""
    applied: list[Config] = []
    told: list[tuple[RoutingMode, bool]] = []
    reconnected: list[Config] = []

    def apply(config: Config) -> list[str]:
        applied.append(config)
        return []

    def dns(config: Config, changed: bool) -> bool:
        assert config.routing is not None
        told.append((config.routing.mode, changed))
        return True

    client, path = box(tmp_path, apply=apply, dns=dns, reconnect=reconnected.append)
    hand_edit(path, "off")
    response = client.post("/config/reread")
    assert response.status_code == 200, response.text
    assert response.json() == {"changed": True, "adguard": "applied"}
    assert [item.routing.mode for item in applied if item.routing] == [RoutingMode.OFF]
    assert told == [(RoutingMode.OFF, False)] and len(reconnected) == 1  # full through vps: direct
    assert client.get("/status").json()["mode"] == "off"
    assert client.post("/config/reread").json() == {"changed": False, "adguard": None}
    assert len(applied) == 1  # nothing new: the router is not rebuilt


def test_a_file_core_cannot_take_leaves_core_as_it_runs(tmp_path: Path) -> None:
    def refused(_config: Config) -> list[str]:
        raise RouterError("nft failed")

    client, path = box(tmp_path)
    path.write_text("version: 1\nrouting: [not, a, mapping]\n", encoding="utf-8")
    assert client.post("/config/reread").status_code == 422
    assert client.get("/status").json()["mode"] == "full"
    client, path = box(tmp_path, apply=refused)
    hand_edit(path, "off")
    answer = client.post("/config/reread")
    assert answer.status_code == 503 and "core keeps its own" in answer.json()["detail"]
    assert client.get("/status").json()["mode"] == "full"


def test_bad_routing_requests_change_nothing(tmp_path: Path) -> None:
    client, path = box(tmp_path)
    before = path.read_text(encoding="utf-8")
    assert client.put("/routing", json={}).status_code == 422
    assert client.put("/routing", json={"mode": "fastest"}).status_code == 422
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
                "vps",
                UPLINKS[Upstream.VPS],
                probe=probe,
                apply=lambda _upstream, _alive: None,
                sleep=sleep,
                report=reports.append,
            )
        )
    assert [item.alive for item in reports] == [True, False]
    assert reports[0].error == "" and "Permission denied" in reports[1].error


def test_watchers_keep_the_state_of_the_uplinks_in_use() -> None:
    async def watch(key: str, _uplink: Uplink, report: object) -> None:
        assert callable(report)
        report(UplinkState(key == "vps", 1.0))
        await asyncio.Event().wait()

    async def scenario() -> None:
        watchers = UplinkWatchers(
            {"vps": UPLINKS[Upstream.VPS], "dpn": UPLINKS[Upstream.DPN]}, watch=watch
        )
        runner = asyncio.ensure_future(watchers.run())
        await asyncio.sleep(0.01)
        assert {k: v.alive for k, v in watchers.states().items()} == {"vps": True, "dpn": False}
        watchers.sync({"vps": UPLINKS[Upstream.VPS]})
        await asyncio.sleep(0.01)
        assert list(watchers.states()) == ["vps"]
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
    assert set_dns_mode(config, tmp_path, transport=httpx.MockTransport(adguard)) is True
    request = seen[0]
    assert str(request.url) == "http://192.168.1.50:3000/control/dns_config"
    assert json.loads(request.content) == {"disable_ipv6": True}
    token = base64.b64encode(f"{CORE_USER}:core-secret-123".encode()).decode()
    assert request.headers["authorization"] == f"Basic {token}"
    refused = httpx.MockTransport(lambda _request: httpx.Response(401))
    with pytest.raises(AdguardError, match="HTTP 401"):
        set_dns_mode(config, tmp_path, transport=refused)
    raw = client_config()
    raw["dns"] = {"enabled": False}
    assert set_dns_mode(Config.model_validate(raw), tmp_path) is None


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


def test_the_vps_tunnel_opens_to_the_lan_live(tmp_path: Path) -> None:
    applied: list[bool] = []

    def apply(config: Config) -> list[Upstream]:
        applied.append(config.upstreams.vps.lan_access)
        return [Upstream.VPS]

    client, path = box(tmp_path, apply=apply)
    vps = next(item for item in client.get("/status").json()["uplinks"] if item["name"] == "vps")
    assert vps["lan_access"] is False  # closed unless the owner opens it
    response = client.put("/uplinks/vps/lan-access", json={"allowed": True})
    assert response.status_code == 200 and response.json() == {"allowed": True}
    assert load_config(path).upstreams.vps.lan_access is True
    assert applied == [True]
    assert "lan_access: true" in path.read_text(encoding="utf-8")
    client, _ = box(tmp_path, vps_config())
    assert client.put("/uplinks/vps/lan-access", json={"allowed": True}).status_code == 404


def test_dpn_country_changes_live_and_countries_come_from_the_consumer(tmp_path: Path) -> None:
    raw = home_config()
    path = tmp_path / "config.yaml"
    path.write_text(render_config(Config.model_validate(raw)), encoding="utf-8")
    config = load_config(path)
    state = BoxState(config, path, apply=lambda _config: [Upstream.DPN])
    offers = [CountryOffer("DE", 2, 100, 90)]
    app = TestClient(create_app(config, state=state, dpn_offers=lambda: offers))
    assert app.get("/dpn/countries").json() == [
        {"country": "DE", "nodes": 2, "min_per_hour_wei": "100", "min_per_gib_wei": "90"}
    ]
    assert app.put("/dpn/country", json={"country": "nl"}).json() == {"country": "NL"}
    assert load_config(path).upstreams.dpn.country == "NL"
    assert app.put("/dpn/country", json={"country": "Netherlands"}).status_code == 422
    assert app.put("/dpn/country", json={"country": None}).json() == {"country": None}

    def silent() -> list[CountryOffer]:
        raise MystError("TequilAPI GET /proposals: HTTP 500")

    silent_app = TestClient(create_app(config, state=state, dpn_offers=silent))
    assert silent_app.get("/dpn/countries").status_code == 503
    client_box, _ = box(tmp_path)  # a client box: dpn is off
    assert client_box.get("/dpn/countries").status_code == 404


def test_status_shows_the_consumer_and_the_gateway_of_every_rule_country() -> None:
    raw = home_config()
    raw["routing"]["mode"] = "smart"
    raw["routing"]["domains"] = [{"domain": "zdf.de", "via": "dpn", "country": "DE"}]
    config = Config.model_validate(raw)
    consumer = ConsumerStatus()
    consumer.states = {
        "dpn": ConsumerState("0xmain", "Registered", "NotConnected", None),
        "dpn-de": ConsumerState("0xde", "Unregistered", "NotConnected", "DE", "not registered"),
    }
    watchers = FakeWatchers({"dpn-de": UplinkState(True, 1_700_000_000.0)})  # type: ignore[dict-item]
    app = create_app(
        config,
        watchers=watchers,  # type: ignore[arg-type]
        routing_reader=lambda _config: FACTS,
        consumer=consumer,
    )
    body = TestClient(app).get("/status").json()
    assert body["dpn"]["identity"] == "0xmain"
    countries = [(item["country"], item["identity"]) for item in body["dpn_countries"]]
    assert countries == [("DE", "0xde")]
    germany = next(item for item in body["uplinks"] if item["name"] == "dpn-de")
    assert germany["enabled"] and germany["in_use"] and germany["gateway_alive"] is True
