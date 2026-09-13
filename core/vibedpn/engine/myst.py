"""TequilAPI client of the Mysterium node and the provider statistics built from it.

The provider node publishes TequilAPI on the host loopback (compose.yaml); it authenticates
nothing, so the client carries no credentials. ``TequilaClient`` is the only I/O; the
``ProviderStats`` assembly is pure and tested on responses captured from a real node.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

import httpx
from pydantic import BaseModel, Field

# Ports compose.yaml publishes for myst-provider on the host loopback; keep equal to compose.yaml.
TEQUILAPI_HOST = "127.0.0.1"
TEQUILAPI_PORT = 4050
NODEUI_PORT = 4449
TEQUILAPI_TIMEOUT_SECONDS = 2.0
# ``provider_stats`` asks the node this many questions, one after another; the CLI waits for
# core at least that long so a slow node reads as "slow", not as "core is not running".
STATS_REQUESTS = 6
STATS_DEADLINE_SECONDS = TEQUILAPI_TIMEOUT_SECONDS * STATS_REQUESTS
WEI_PER_MYST = Decimal(10) ** 18
BYTES_PER_UNIT = 1024
FRACTIONAL_SECONDS = re.compile(r"(\d+)\.\d+s$")
SUB_SECOND = re.compile(r"^\d+(\.\d+)?(ms|µs|us|ns)$")


class MystError(RuntimeError):
    """The node did not answer, or answered something the client cannot read."""


class Tokens(BaseModel):
    """A MYST amount as the node reports it (``wei`` is the exact value)."""

    wei: str = "0"
    human: str = "0"

    @property
    def myst(self) -> Decimal:
        try:
            return Decimal(self.wei) / WEI_PER_MYST
        except InvalidOperation:
            return Decimal(0)


class Identity(BaseModel):
    id: str
    registration_status: str
    balance_tokens: Tokens = Tokens()
    earnings_tokens: Tokens = Tokens()
    earnings_total_tokens: Tokens = Tokens()


class Service(BaseModel):
    type: str
    status: str


class SessionTotals(BaseModel):
    count: int = 0
    consumers: int = 0
    bytes_received: int = 0
    bytes_sent: int = 0
    duration_seconds: int = 0
    tokens_myst: Decimal = Decimal(0)


class ProviderStats(BaseModel):
    """What ``GET /provider/stats`` returns; fields stay stable for the UI.

    Only ``/healthcheck`` is mandatory: a question the node did not answer leaves its field at
    the default and its reason in ``problems``, so one slow endpoint never hides the rest.
    """

    node_version: str
    node_uptime: str
    monitoring_status: str
    identity: Identity | None
    services: list[Service]
    sessions: SessionTotals
    problems: list[str] = Field(default_factory=list)


class TequilaClient:
    """Thin HTTP client; every failure becomes ``MystError`` with the endpoint in the text."""

    def __init__(
        self, base_url: str | None = None, transport: httpx.BaseTransport | None = None
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url or f"http://{TEQUILAPI_HOST}:{TEQUILAPI_PORT}",
            timeout=TEQUILAPI_TIMEOUT_SECONDS,
            transport=transport,
            trust_env=False,  # loopback: never through an HTTP_PROXY of the environment
        )

    def get(self, path: str) -> object:
        try:
            response = self._client.get(path)
        except httpx.HTTPError as exc:
            raise MystError(f"TequilAPI {path}: {exc.__class__.__name__}: {exc}") from exc
        if response.status_code != httpx.codes.OK:
            raise MystError(f"TequilAPI {path}: HTTP {response.status_code}")
        try:
            body: object = response.json()
        except ValueError as exc:
            raise MystError(f"TequilAPI {path}: not JSON") from exc
        return body

    def close(self) -> None:
        self._client.close()


# The node's JSON is read defensively: a missing or oddly typed field degrades to a default
# instead of failing the whole answer, because the UI must keep showing the rest.
def _dict(raw: object) -> dict[str, object]:
    return raw if isinstance(raw, dict) else {}


def _list(raw: object) -> list[object]:
    return raw if isinstance(raw, list) else []


def _str(raw: object, default: str) -> str:
    return raw if isinstance(raw, str) and raw else default


def _int(raw: object) -> int:
    return raw if isinstance(raw, int) and not isinstance(raw, bool) else 0


def _tokens(raw: object) -> Tokens:
    fields = _dict(raw)
    return Tokens(wei=_str(fields.get("wei"), "0"), human=_str(fields.get("human"), "0"))


def _myst(raw: object) -> Decimal:
    """``sum_tokens`` is a ``math/big.Int`` of wei: a JSON number on the wire (``0`` on a fresh
    node), a string in the swagger; both are read exactly."""
    try:
        return Decimal(str(raw)) / WEI_PER_MYST
    except InvalidOperation:
        return Decimal(0)


def first_identity_id(identities: object) -> str | None:
    """The ``id`` of the first entry of ``GET /identities`` (a list of ``IdentityRefDTO``:
    the id and nothing else — status and balances live in ``GET /identities/{id}``)."""
    first = _dict(next(iter(_list(_dict(identities).get("identities"))), None))
    return _str(first.get("id"), "") or None


def _identity(identity_id: str | None, detail: object) -> Identity | None:
    if identity_id is None:
        return None
    fields = _dict(detail)
    return Identity(
        id=_str(fields.get("id"), identity_id),
        registration_status=_str(fields.get("registration_status"), "Unknown"),
        balance_tokens=_tokens(fields.get("balance_tokens")),
        earnings_tokens=_tokens(fields.get("earnings_tokens")),
        earnings_total_tokens=_tokens(fields.get("earnings_total_tokens")),
    )


def build_stats(
    healthcheck: object,
    identities: object,
    identity_detail: object,
    services: object,
    session_stats: object,
    monitoring: object,
    problems: list[str] | None = None,
) -> ProviderStats:
    """Pure assembly of the raw TequilAPI answers into ``ProviderStats``."""
    health = _dict(healthcheck)
    stats = _dict(_dict(session_stats).get("stats"))
    return ProviderStats(
        node_version=_str(health.get("version"), "?"),
        node_uptime=_str(health.get("uptime"), "?"),
        monitoring_status=_str(_dict(monitoring).get("status"), "unknown"),
        identity=_identity(first_identity_id(identities), identity_detail),
        services=[
            Service(
                type=_str(_dict(item).get("type"), "?"), status=_str(_dict(item).get("status"), "?")
            )
            for item in _list(services)
        ],
        sessions=SessionTotals(
            count=_int(stats.get("count")),
            consumers=_int(stats.get("count_consumers")),
            bytes_received=_int(stats.get("sum_bytes_received")),
            bytes_sent=_int(stats.get("sum_bytes_sent")),
            duration_seconds=_int(stats.get("sum_duration")),
            tokens_myst=_myst(stats.get("sum_tokens", 0)),
        ),
        problems=list(problems or []),
    )


def human_bytes(count: int) -> str:
    """``1536`` → ``1.5 KiB``; whole bytes stay as they are."""
    value = float(count)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < BYTES_PER_UNIT or unit == "TiB":
            return f"{count} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= BYTES_PER_UNIT
    raise AssertionError("unreachable")


def short_uptime(uptime: str) -> str:
    """``72h3m5.123456789s`` (a Go duration) → ``72h3m5s``, ``192.85ms`` → ``<1s``; anything
    else is left alone."""
    if SUB_SECOND.match(uptime):
        return "<1s"
    return FRACTIONAL_SECONDS.sub(r"\1s", uptime)


def render_stats(stats: ProviderStats) -> list[str]:
    """The ``node`` block of ``vibedpn status``: one line per thing an owner asks about."""
    lines = [
        f"node: myst {stats.node_version}, up {short_uptime(stats.node_uptime)},"
        f" monitoring {stats.monitoring_status}"
    ]
    identity = stats.identity
    if identity is None:
        lines.append("identity: none yet (the node creates one on its first start)")
    else:
        lines.append(
            f"identity: {identity.id} {identity.registration_status},"
            f" balance {identity.balance_tokens.myst:f} MYST,"
            f" earnings {identity.earnings_tokens.myst:f} MYST"
            f" (total {identity.earnings_total_tokens.myst:f} MYST)"
        )
    services = ", ".join(f"{item.type} {item.status}" for item in stats.services) or "none"
    lines.append(f"services: {services}")
    totals = stats.sessions
    lines.append(
        f"sessions: {totals.count} ({totals.consumers} consumers),"
        f" rx {human_bytes(totals.bytes_received)}, tx {human_bytes(totals.bytes_sent)},"
        f" {totals.tokens_myst:f} MYST"
    )
    if stats.problems:
        lines.append(f"problems: {'; '.join(stats.problems)}")
    return lines


def provider_stats(client: TequilaClient) -> ProviderStats:
    """Ask the node its questions and assemble the answer.

    ``/healthcheck`` failing means the node is unreachable and raises; any other question the
    node fails (``/node/monitoring-status`` waits on an external oracle, ``/identities/{id}`` on
    the blockchain) is recorded in ``problems`` and its field stays at the default.
    """
    problems: list[str] = []

    def ask(path: str) -> object:
        try:
            return client.get(path)
        except MystError as exc:
            problems.append(str(exc))
            return None

    healthcheck = client.get("/healthcheck")
    identities = ask("/identities")
    identity_id = first_identity_id(identities)
    detail = ask(f"/identities/{identity_id}") if identity_id else None
    return build_stats(
        healthcheck,
        identities,
        detail,
        ask("/services"),
        ask("/sessions/stats-aggregated"),
        ask("/node/monitoring-status"),
        problems,
    )


# NAT types of the node (nat/types.go of node 1.39.5): how peers can reach it.
NAT_OPEN = frozenset({"none", "fullcone"})
NAT_PUNCHABLE = frozenset({"rcone", "prcone"})
NAT_SYMMETRIC = "symmetric"


def nat_type(client: TequilaClient) -> str:
    """``GET /nat/type``: the node's own probe of its NAT. It asks Mysterium's servers, so it is
    a network action; the answer is the node's estimate, not a test of the published ports."""
    body = client.get("/nat/type")
    if not isinstance(body, dict) or not isinstance(body.get("type"), str):
        raise MystError("TequilAPI /nat/type: unexpected answer")
    return str(body["type"])
