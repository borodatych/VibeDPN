"""Bodies of the core API that the CLI reads back: one definition for both sides."""

from datetime import datetime
from ipaddress import IPv4Address

from pydantic import BaseModel


class PeerCreate(BaseModel):
    name: str
    tunnel_only: bool = False


class PeerView(BaseModel):
    """A peer as ``GET /peers`` lists it — never with its private key.

    The live fields come from the running interface and are ``None`` when core cannot read it.
    """

    name: str
    address: IPv4Address
    public_key: str
    created: datetime
    endpoint: str | None = None
    latest_handshake: int | None = None  # unix seconds; 0 means no handshake yet
    rx_bytes: int | None = None
    tx_bytes: int | None = None
    # None: core cannot read the interface; False: registered, not on wg0 yet (wg-server applies
    # a change within seconds, so a peer that stays False points at wg-server); True: on wg0.
    applied: bool | None = None
    tunnel_only: bool = False


class PeerFile(BaseModel):
    """A peer's WireGuard file, from ``POST /peers`` and ``GET /peers/{name}/config``."""

    name: str
    address: IPv4Address
    config: str
