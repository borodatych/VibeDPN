"""TequilAPI client and the provider statistics built from recorded node answers."""

import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from vibedpn.engine.myst import (
    Identity,
    MystError,
    ProviderStats,
    TequilaClient,
    Tokens,
    build_stats,
    human_bytes,
    nat_type,
    provider_stats,
    render_stats,
    short_uptime,
)

FIXTURES = Path(__file__).parent / "fixtures" / "tequilapi"

# Answers of myst 1.39.5 right after the first start: no identity, no service, no sessions.
FRESH_ROUTES = {
    "/healthcheck": "healthcheck.json",
    "/identities": "identities.json",
    "/services": "services.json",
    "/sessions/stats-aggregated": "sessions_stats_aggregated.json",
    "/node/monitoring-status": "monitoring_status.json",
}
IDENTITY = "0x1234567890abcdef1234567890abcdef12345678"

# A working node, shaped by the swagger definitions: the list holds IdentityRefDTO (id only),
# the detail an IdentityDTO; ServiceInfoDTO; SessionStatsDTO.
BUSY_ROUTES: dict[str, object] = {
    "/healthcheck": {"uptime": "72h3m", "process": 1, "version": "1.39.5"},
    "/identities": {"identities": [{"id": IDENTITY}]},
    f"/identities/{IDENTITY}": {
        "id": IDENTITY,
        "registration_status": "Registered",
        "balance_tokens": {"wei": "1500000000000000000", "ether": "1.5", "human": "1.5"},
        "earnings_tokens": {"wei": "250000000000000000", "ether": "0.25", "human": "0.25"},
        "earnings_total_tokens": {"wei": "3000000000000000000", "ether": "3", "human": "3"},
        "hermes_id": "0xhermes",
        "channel_address": "0xchannel",
        "stake": {"wei": "0", "ether": "0", "human": "0"},
    },
    "/services": [
        {"id": "s1", "provider_id": "0x1234", "status": "Running", "type": "wireguard"},
        {"id": "s2", "provider_id": "0x1234", "status": "Starting", "type": "scraping"},
    ],
    "/sessions/stats-aggregated": {
        "stats": {
            "count": 12,
            "count_consumers": 7,
            "sum_bytes_received": 1572864,
            "sum_bytes_sent": 5368709120,
            "sum_duration": 86400,
            "sum_tokens": "250000000000000000",
        }
    },
    "/node/monitoring-status": {"status": "passed"},
}


def fixture(name: str) -> object:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


ORDER = (
    "/healthcheck",
    "/identities",
    f"/identities/{IDENTITY}",
    "/services",
    "/sessions/stats-aggregated",
    "/node/monitoring-status",
)


def assemble(answers: dict[str, object]) -> ProviderStats:
    """``build_stats`` fed in the order ``provider_stats`` asks; a missing answer is ``None``."""
    health, ids, detail, services, sessions, monitoring = (answers.get(path) for path in ORDER)
    return build_stats(health, ids, detail, services, sessions, monitoring)


def fresh_stats() -> ProviderStats:
    return assemble({path: fixture(name) for path, name in FRESH_ROUTES.items()})


def busy_stats() -> ProviderStats:
    return assemble(BUSY_ROUTES)


def transport(routes: dict[str, object], status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = routes[request.url.path]
        if isinstance(body, Exception):
            raise body
        content = json.dumps(body) if not isinstance(body, str) else body
        return httpx.Response(status, content=content)

    return httpx.MockTransport(handler)


def test_fresh_node_has_no_identity_services_or_sessions() -> None:
    stats = fresh_stats()
    assert stats.node_version == "1.39.5"
    assert stats.node_uptime == "6.194346087s"
    assert stats.monitoring_status == "unknown"
    assert stats.identity is None
    assert stats.services == []
    assert stats.sessions.count == 0
    assert stats.sessions.tokens_myst == 0


def test_busy_node_is_read_field_by_field() -> None:
    stats = busy_stats()
    assert stats.identity is not None
    assert stats.identity.id.startswith("0x1234")
    assert stats.identity.registration_status == "Registered"
    assert stats.identity.balance_tokens.myst == Decimal("1.5")
    assert stats.identity.earnings_tokens.myst == Decimal("0.25")
    assert stats.identity.earnings_total_tokens.myst == Decimal(3)
    assert [(s.type, s.status) for s in stats.services] == [
        ("wireguard", "Running"),
        ("scraping", "Starting"),
    ]
    totals = stats.sessions
    assert (totals.count, totals.consumers) == (12, 7)
    assert (totals.bytes_received, totals.bytes_sent) == (1572864, 5368709120)
    assert totals.duration_seconds == 86400
    assert totals.tokens_myst == Decimal("0.25")
    assert stats.monitoring_status == "passed"


def test_unexpected_shapes_degrade_to_defaults() -> None:
    stats = build_stats(
        ["not", "a", "dict"],
        {"identities": [{"id": IDENTITY}]},
        {"id": 42, "balance_tokens": "oops"},
        {"services": "not a list"},
        {"stats": {"count": "12", "sum_tokens": "garbage", "sum_bytes_sent": True}},
        None,
    )
    assert stats.node_version == "?"
    assert stats.identity is not None
    assert stats.identity.id == IDENTITY
    assert stats.identity.registration_status == "Unknown"
    assert stats.identity.balance_tokens == Tokens()
    assert stats.services == []
    assert stats.sessions.count == 0
    assert stats.sessions.bytes_sent == 0
    assert stats.sessions.tokens_myst == 0
    assert stats.monitoring_status == "unknown"


def test_tokens_convert_wei_to_myst() -> None:
    assert Tokens(wei="1000000000000000000").myst == Decimal(1)
    assert Tokens(wei="1").myst == Decimal("0.000000000000000001")
    assert Tokens(wei="not a number").myst == Decimal(0)


def test_client_reads_fresh_fixtures_over_http() -> None:
    routes = {path: fixture(name) for path, name in FRESH_ROUTES.items()}
    client = TequilaClient(transport=transport(routes))
    try:
        assert provider_stats(client) == fresh_stats()
    finally:
        client.close()


def test_client_asks_the_identity_detail_for_the_first_identity() -> None:
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.path)
        return httpx.Response(200, content=json.dumps(BUSY_ROUTES[request.url.path]))

    client = TequilaClient(transport=httpx.MockTransport(handler))
    try:
        assert provider_stats(client) == busy_stats()
    finally:
        client.close()
    assert asked == list(ORDER)


def test_only_healthcheck_is_mandatory() -> None:
    """A slow oracle behind /node/monitoring-status must not hide identity and sessions."""
    routes: dict[str, object] = dict(BUSY_ROUTES)
    request = httpx.Request("GET", "http://127.0.0.1:4050/node/monitoring-status")
    routes["/node/monitoring-status"] = httpx.ReadTimeout("timed out", request=request)
    client = TequilaClient(transport=transport(routes))
    try:
        stats = provider_stats(client)
    finally:
        client.close()
    assert stats.monitoring_status == "unknown"
    assert stats.identity is not None and stats.identity.registration_status == "Registered"
    assert stats.sessions.count == 12
    assert stats.problems == ["TequilAPI /node/monitoring-status: ReadTimeout: timed out"]
    assert render_stats(stats)[-1] == (
        "problems: TequilAPI /node/monitoring-status: ReadTimeout: timed out"
    )


def test_identity_detail_failure_keeps_the_id() -> None:
    """``GET /identities/{id}`` walks to the blockchain and may 500; the id is still known."""
    routes: dict[str, object] = dict(BUSY_ROUTES)
    routes[f"/identities/{IDENTITY}"] = {"error": "blockchain unavailable"}

    def handler(request: httpx.Request) -> httpx.Response:
        status = 500 if request.url.path.startswith("/identities/") else 200
        return httpx.Response(status, content=json.dumps(routes[request.url.path]))

    client = TequilaClient(transport=httpx.MockTransport(handler))
    try:
        stats = provider_stats(client)
    finally:
        client.close()
    assert stats.identity == Identity(id=IDENTITY, registration_status="Unknown")
    assert stats.problems == [f"TequilAPI /identities/{IDENTITY}: HTTP 500"]


def test_healthcheck_failure_raises() -> None:
    routes: dict[str, object] = dict(BUSY_ROUTES)
    request = httpx.Request("GET", "http://127.0.0.1:4050/healthcheck")
    routes["/healthcheck"] = httpx.ConnectError("refused", request=request)
    client = TequilaClient(transport=transport(routes))
    with pytest.raises(MystError, match="/healthcheck: ConnectError"):
        provider_stats(client)
    client.close()


@pytest.mark.parametrize(
    ("routes", "status", "expected"),
    [
        ({"/healthcheck": {}}, 500, "HTTP 500"),
        ({"/healthcheck": "<html>"}, 200, "not JSON"),
    ],
)
def test_client_turns_bad_answers_into_myst_error(
    routes: dict[str, object], status: int, expected: str
) -> None:
    client = TequilaClient(transport=transport(routes, status))
    with pytest.raises(MystError, match=rf"TequilAPI /healthcheck: {expected}"):
        client.get("/healthcheck")


def test_client_turns_connection_failure_into_myst_error() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = TequilaClient(transport=httpx.MockTransport(refuse))
    with pytest.raises(MystError, match=r"TequilAPI /healthcheck: ConnectError"):
        client.get("/healthcheck")


def test_client_default_base_url_is_host_loopback() -> None:
    client = TequilaClient()
    assert str(client._client.base_url) == "http://127.0.0.1:4050"
    client.close()


def test_render_fresh_node() -> None:
    assert render_stats(fresh_stats()) == [
        "node: myst 1.39.5, up 6s, monitoring unknown",
        "identity: none yet (the node creates one on its first start)",
        "services: none",
        "sessions: 0 (0 consumers), rx 0 B, tx 0 B, 0 MYST",
    ]


def test_render_busy_node() -> None:
    assert render_stats(busy_stats()) == [
        "node: myst 1.39.5, up 72h3m, monitoring passed",
        "identity: 0x1234567890abcdef1234567890abcdef12345678 Registered,"
        " balance 1.5 MYST, earnings 0.25 MYST (total 3 MYST)",
        "services: wireguard Running, scraping Starting",
        "sessions: 12 (7 consumers), rx 1.5 MiB, tx 5.0 GiB, 0.25 MYST",
    ]


@pytest.mark.parametrize(
    ("count", "expected"),
    [(0, "0 B"), (1023, "1023 B"), (1024, "1.0 KiB"), (1536, "1.5 KiB"), (2**40 * 3, "3.0 TiB")],
)
def test_human_bytes(count: int, expected: str) -> None:
    assert human_bytes(count) == expected


@pytest.mark.parametrize(
    ("uptime", "expected"),
    [
        ("6.194346087s", "6s"),
        ("72h3m5.123456789s", "72h3m5s"),
        ("72h3m", "72h3m"),
        ("192.854845ms", "<1s"),
        ("321.095µs", "<1s"),
        ("?", "?"),
    ],
)
def test_short_uptime(uptime: str, expected: str) -> None:
    assert short_uptime(uptime) == expected


def test_stats_round_trip_through_json() -> None:
    stats = busy_stats()
    assert ProviderStats.model_validate_json(stats.model_dump_json()) == stats


def test_nat_type_reads_the_node_probe() -> None:
    def answering(body: object) -> TequilaClient:
        return TequilaClient(
            transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=body))
        )

    assert nat_type(answering({"type": "prcone"})) == "prcone"
    with pytest.raises(MystError, match="unexpected"):
        nat_type(answering({"kind": 1}))
