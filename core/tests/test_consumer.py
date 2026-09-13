"""The dpn consumer round: identity, unlock, registration gate, connect with the kill switch on."""

import asyncio
import contextlib
import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from vibedpn.api import consumer as consumer_module
from vibedpn.api.consumer import ConsumerStatus, consumer_round, watch_consumer
from vibedpn.config import Config
from vibedpn.engine.consumer import CONSUMER_TIMEOUT_SECONDS, ConsumerState, countries, reconcile
from vibedpn.engine.myst import TEQUILAPI_TIMEOUT_SECONDS, TequilaClient

from .conftest import home_config

IDENTITY = "0xabc"


class FakeNode:
    def __init__(self, *, identities: list[str], registration: str, connection: str) -> None:
        self.identities = identities
        self.registration = registration
        self.connection = connection
        self.calls: list[tuple[str, str, object]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        path = request.url.path
        self.calls.append((request.method, path, body))
        if request.method == "PUT" and path.endswith("/unlock"):
            return httpx.Response(202)
        route = self.routes().get((request.method, path))
        return route() if route else httpx.Response(404)

    def routes(self) -> dict[tuple[str, str], Callable[[], httpx.Response]]:
        return {
            ("GET", "/identities"): lambda: httpx.Response(
                200, json={"identities": [{"id": i} for i in self.identities]}
            ),
            ("POST", "/identities"): self.create,
            ("GET", f"/identities/{IDENTITY}"): lambda: httpx.Response(
                200, json={"id": IDENTITY, "registration_status": self.registration}
            ),
            ("GET", "/connection"): lambda: httpx.Response(200, json={"status": self.connection}),
            ("PUT", "/connection"): self.connect,
            ("DELETE", "/connection"): self.disconnect,
        }

    def create(self) -> httpx.Response:
        self.identities.append(IDENTITY)
        return httpx.Response(200, json={"id": IDENTITY})

    def connect(self) -> httpx.Response:
        self.connection = "Connected"
        return httpx.Response(201, json={"status": "Connecting"})

    def disconnect(self) -> httpx.Response:
        self.connection = "NotConnected"
        return httpx.Response(202)


def client(node: FakeNode) -> TequilaClient:
    return TequilaClient(base_url="http://consumer", transport=httpx.MockTransport(node))


def test_a_fresh_node_gets_an_identity_but_no_registration_and_no_connect() -> None:
    node = FakeNode(identities=[], registration="Unregistered", connection="NotConnected")
    state = reconcile(client(node), "secret", "DE", wanted=True)
    assert state.identity == IDENTITY and state.registration == "Unregistered"
    assert "not registered" in state.error
    assert ("POST", "/identities", {"passphrase": "secret"}) in node.calls
    assert not [call for call in node.calls if "register" in call[1]]  # the owner registers
    assert not [call for call in node.calls if call[:2] == ("PUT", "/connection")]


def test_a_registered_identity_connects_with_the_kill_switch_on() -> None:
    node = FakeNode(identities=[IDENTITY], registration="Registered", connection="NotConnected")
    state = reconcile(client(node), "secret", "DE", wanted=True)
    assert state.error == "" and state.connection == "Connecting"
    connect = next(call for call in node.calls if call[:2] == ("PUT", "/connection"))
    assert connect[2] == {
        "consumer_id": IDENTITY,
        "service_type": "wireguard",
        "filter": {"country_code": "DE"},
    }
    assert "connect_options" not in json.dumps(connect[2])  # kill_switch: true would disable it


def test_an_unused_uplink_is_disconnected() -> None:
    node = FakeNode(identities=[IDENTITY], registration="Registered", connection="Connected")
    state = reconcile(client(node), "secret", None, wanted=False)
    assert state.connection == "NotConnected"
    assert ("DELETE", "/connection", None) in node.calls


def test_a_silent_node_ends_the_round_in_an_error() -> None:
    silent = TequilaClient(
        base_url="http://consumer",
        transport=httpx.MockTransport(
            lambda _r: (_ for _ in ()).throw(httpx.ConnectError("refused"))
        ),
    )
    state = reconcile(silent, "secret", "DE", wanted=True)
    assert state.identity is None and "ConnectError" in state.error


def test_the_round_needs_the_passphrase_secret(tmp_path: Path) -> None:
    state = consumer_round(tmp_path)(Config.model_validate(home_config()))
    assert "myst-consumer-passphrase" in state.error


def test_watch_keeps_the_last_state_only_while_dpn_is_enabled() -> None:
    config = Config.model_validate(home_config())
    status = ConsumerStatus()
    rounds = 0

    async def sleep(_seconds: float) -> None:
        nonlocal rounds
        rounds += 1
        if rounds == 1:
            raise asyncio.CancelledError

    def step(_config: Config) -> ConsumerState:
        return ConsumerState(IDENTITY, "Unregistered", "NotConnected", None, "not registered")

    with contextlib.suppress(asyncio.CancelledError):
        asyncio.run(watch_consumer(lambda: config, status, step, sleep=sleep))
    assert status.state is not None and status.state.identity == IDENTITY


def test_the_consumer_client_waits_for_the_blockchain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "myst-consumer-passphrase").write_text("secret", encoding="utf-8")
    seen: list[float] = []
    unavailable = httpx.MockTransport(lambda _r: httpx.Response(503))

    class Recording(TequilaClient):
        def __init__(
            self, base_url: str | None = None, transport: object = None, timeout: float = 0
        ) -> None:
            seen.append(timeout)
            super().__init__(base_url=base_url, transport=unavailable, timeout=timeout)

    monkeypatch.setattr(consumer_module, "TequilaClient", Recording)
    consumer_round(tmp_path)(Config.model_validate(home_config()))
    assert seen == [CONSUMER_TIMEOUT_SECONDS]
    assert CONSUMER_TIMEOUT_SECONDS > TEQUILAPI_TIMEOUT_SECONDS


def test_a_changed_country_drops_the_live_session() -> None:
    node = FakeNode(identities=[IDENTITY], registration="Registered", connection="Connected")
    original = node.routes

    def routes() -> dict[tuple[str, str], Callable[[], httpx.Response]]:
        table = original()
        table[("GET", "/connection")] = lambda: httpx.Response(
            200, json={"status": node.connection, "proposal": {"location": {"country": "nl"}}}
        )
        return table

    node.routes = routes  # type: ignore[method-assign]
    state = reconcile(client(node), "secret", "DE", wanted=True)
    assert state.connection == "NotConnected"
    assert ("DELETE", "/connection", None) in node.calls


def test_countries_group_the_proposals_with_the_lowest_prices() -> None:
    def offer(country: str | None, hour: str, gib: str) -> dict[str, object]:
        price = {"per_hour_tokens": {"wei": hour}, "per_gib_tokens": {"wei": gib}}
        return {"location": {"country": country} if country else {}, "price": price}

    proposals = {
        "proposals": [
            offer("de", "300", "90"),
            offer("DE", "100", "120"),
            offer("NL", "50", "70"),
            offer(None, "0", "0"),
        ]
    }
    seen: list[str] = []

    def node(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=proposals)

    offers = countries(
        TequilaClient(base_url="http://consumer", transport=httpx.MockTransport(node))
    )
    assert [(o.country, o.nodes, o.min_per_hour_wei, o.min_per_gib_wei) for o in offers] == [
        ("DE", 2, 100, 90),
        ("NL", 1, 50, 70),
    ]
    assert seen == ["http://consumer/proposals?service_type=wireguard"]
