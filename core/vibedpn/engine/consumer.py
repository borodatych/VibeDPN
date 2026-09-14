"""The Mysterium consumer of uplink dpn, driven through its TequilAPI (node 1.39.5).

One round brings the consumer toward config.yaml: an identity exists and is unlocked with the
passphrase from ``secrets/``, and it is connected into ``upstreams.dpn.country`` while uplink dpn
is in use. Registration is never started here: it is a transaction on the Mysterium network and
may cost a fee, so the owner starts it (docs/decisions.md). The kill switch stays on: the connect
request carries no ``kill_switch`` field, because ``kill_switch: true`` *disables* it
(knowledge myst/consumer.md).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from vibedpn.engine.myst import MystError, TequilaClient

TEQUILAPI_PORT = 4050  # --tequilapi.address of myst-consumer in compose.yaml


def tequilapi_url(gateway: str) -> str:
    """TequilAPI of a consumer container at its gateway address."""
    return f"http://{gateway}:{TEQUILAPI_PORT}"


CONSUMER_TEQUILAPI = tequilapi_url("10.77.0.20")  # the gateway address of dpn in compose.yaml
# `GET /identities/{id}` asks the blockchain for registration and balance: seconds, not the
# fraction of a second the provider statistics take (a 2 s timeout failed on the home stand).
CONSUMER_TIMEOUT_SECONDS = 20.0
SERVICE_TYPE = "wireguard"
REGISTERED = "Registered"
REGISTRATION_IN_PROGRESS = "InProgress"
CONNECTED = "Connected"
NOT_CONNECTED = "NotConnected"
HTTP_OK = 200
HTTP_CREATED = 201
HTTP_ACCEPTED = 202


@dataclass(frozen=True)
class ConsumerState:
    """What the consumer is now; ``error`` says why it is not where config.yaml wants it."""

    identity: str | None
    registration: str
    connection: str
    country: str | None
    error: str = ""
    balance_wei: str = "0"  # MYST in wei; before registration it is the MYST on channel_address
    channel_address: str = ""  # where MYST on Polygon tops the consumer up


def _field(body: object, name: str) -> str:
    value = body.get(name) if isinstance(body, dict) else None
    return value if isinstance(value, str) else ""


def _identity(client: TequilaClient, passphrase: str) -> str:
    status, body = client.send("GET", "/identities")
    if status != HTTP_OK:
        raise MystError(f"TequilAPI GET /identities: HTTP {status}")
    listed = body.get("identities") if isinstance(body, dict) else None
    first = listed[0] if isinstance(listed, list) and listed else None
    identity = _field(first, "id")
    if identity:
        return identity
    status, body = client.send("POST", "/identities", {"passphrase": passphrase})
    identity = _field(body, "id")
    if status != HTTP_OK or not identity:
        raise MystError(f"TequilAPI POST /identities: HTTP {status}")
    return identity


def reconcile(
    client: TequilaClient, passphrase: str, country: str | None, wanted: bool
) -> ConsumerState:
    """One round toward config.yaml; failures of the node end the round in ``error``. The
    balance and the top-up address come along whenever the node gave them."""
    known: dict[str, str] = {}
    state = _round(client, passphrase, country, wanted, known)
    return replace(
        state,
        balance_wei=known.get("balance_wei", "0"),
        channel_address=known.get("channel_address", ""),
    )


def _round(
    client: TequilaClient,
    passphrase: str,
    country: str | None,
    wanted: bool,
    known: dict[str, str],
) -> ConsumerState:
    identity: str | None = None
    registration = "Unknown"
    connection = "Unknown"
    try:
        identity = _identity(client, passphrase)
        status, _ = client.send("PUT", f"/identities/{identity}/unlock", {"passphrase": passphrase})
        if status not in (HTTP_OK, HTTP_ACCEPTED):
            return ConsumerState(
                identity, registration, connection, country, f"unlock: HTTP {status}"
            )
        status, body = client.send("GET", f"/identities/{identity}")
        registration = _field(body, "registration_status") or "Unknown"
        balance = body.get("balance_tokens") if isinstance(body, dict) else None
        known["balance_wei"] = _field(balance, "wei") or "0"
        known["channel_address"] = _field(body, "channel_address")
        status, body = client.send("GET", "/connection")
        connection = _field(body, "status") or "Unknown"
        session_country = _session_country(body)
        if not wanted:
            if connection != NOT_CONNECTED:
                client.send("DELETE", "/connection")
                connection = NOT_CONNECTED
            return ConsumerState(identity, registration, connection, country)
        if registration not in (REGISTERED, REGISTRATION_IN_PROGRESS):
            return ConsumerState(
                identity,
                registration,
                connection,
                country,
                "the consumer identity is not registered: register it and top it up with MYST",
            )
        if connection != NOT_CONNECTED and country and session_country not in ("", country):
            # upstreams.dpn.country changed under a live session: drop it, the next round connects
            client.send("DELETE", "/connection")
            return ConsumerState(identity, registration, NOT_CONNECTED, country)
        return _connect(client, identity, registration, connection, country)
    except MystError as exc:
        return ConsumerState(identity, registration, connection, country, str(exc))


def _connect(
    client: TequilaClient, identity: str, registration: str, connection: str, country: str | None
) -> ConsumerState:
    """Connect a registered identity that has no session yet; the kill switch stays on."""
    if connection != NOT_CONNECTED:
        return ConsumerState(identity, registration, connection, country)
    request: dict[str, object] = {"consumer_id": identity, "service_type": SERVICE_TYPE}
    if country:
        request["filter"] = {"country_code": country}
    status, body = client.send("PUT", "/connection", request)
    if status not in (HTTP_OK, HTTP_CREATED):
        error = f"connect: {_field(body, 'message') or f'HTTP {status}'}"
        return ConsumerState(identity, registration, connection, country, error)
    return ConsumerState(identity, registration, _field(body, "status") or connection, country)


def _session_country(body: object) -> str:
    """The country of the node a session runs through (``proposal.location.country``)."""
    proposal = body.get("proposal") if isinstance(body, dict) else None
    location = proposal.get("location") if isinstance(proposal, dict) else None
    return _field(location, "country").upper()


@dataclass(frozen=True)
class CountryOffer:
    """Nodes of one country that sell the dpn service type, and their lowest prices."""

    country: str
    nodes: int
    min_per_hour_wei: int
    min_per_gib_wei: int


def _wei(price: object, name: str) -> int:
    tokens = price.get(name) if isinstance(price, dict) else None
    raw = tokens.get("wei") if isinstance(tokens, dict) else None
    try:
        return int(str(raw))
    except ValueError:
        return 0


def countries(client: TequilaClient) -> list[CountryOffer]:
    """``GET /proposals`` of the consumer node grouped by country, sorted by country code."""
    status, body = client.send("GET", f"/proposals?service_type={SERVICE_TYPE}")
    if status != HTTP_OK:
        raise MystError(f"TequilAPI GET /proposals: HTTP {status}")
    listed = body.get("proposals") if isinstance(body, dict) else None
    grouped: dict[str, list[tuple[int, int]]] = {}
    for proposal in listed if isinstance(listed, list) else []:
        if not isinstance(proposal, dict):
            continue
        code = _field(proposal.get("location"), "country").upper()
        if not code:
            continue
        price = proposal.get("price")
        grouped.setdefault(code, []).append(
            (_wei(price, "per_hour_tokens"), _wei(price, "per_gib_tokens"))
        )
    return [
        CountryOffer(
            country=code,
            nodes=len(prices),
            min_per_hour_wei=min(hour for hour, _ in prices),
            min_per_gib_wei=min(gib for _, gib in prices),
        )
        for code, prices in sorted(grouped.items())
    ]
