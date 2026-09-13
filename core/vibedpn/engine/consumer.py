"""The Mysterium consumer of uplink dpn, driven through its TequilAPI (node 1.39.5).

One round brings the consumer toward config.yaml: an identity exists and is unlocked with the
passphrase from ``secrets/``, and it is connected into ``upstreams.dpn.country`` while uplink dpn
is in use. Registration is never started here: it is a transaction on the Mysterium network and
may cost a fee, so the owner starts it (docs/decisions.md). The kill switch stays on: the connect
request carries no ``kill_switch`` field, because ``kill_switch: true`` *disables* it
(knowledge myst/consumer.md).
"""

from __future__ import annotations

from dataclasses import dataclass

from vibedpn.engine.myst import MystError, TequilaClient

CONSUMER_TEQUILAPI = "http://10.77.0.20:4050"  # the gateway address of dpn in compose.yaml
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
    """One round toward config.yaml; failures of the node end the round in ``error``."""
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
        status, body = client.send("GET", "/connection")
        connection = _field(body, "status") or "Unknown"
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
        if connection == NOT_CONNECTED:
            request: dict[str, object] = {"consumer_id": identity, "service_type": SERVICE_TYPE}
            if country:
                request["filter"] = {"country_code": country}
            status, body = client.send("PUT", "/connection", request)
            if status not in (HTTP_OK, HTTP_CREATED):
                message = _field(body, "message") or f"HTTP {status}"
                return ConsumerState(
                    identity, registration, connection, country, f"connect: {message}"
                )
            connection = _field(body, "status") or connection
        return ConsumerState(identity, registration, connection, country)
    except MystError as exc:
        return ConsumerState(identity, registration, connection, country, str(exc))
