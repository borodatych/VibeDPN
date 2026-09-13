"""Bodies of the core API that the CLI reads back: one definition for both sides."""

from datetime import datetime
from ipaddress import IPv4Address
from typing import Literal

from pydantic import BaseModel, Field

from vibedpn.config import DevicePolicy, Upstream


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


class DeviceView(BaseModel):
    """A LAN device: seen by discovery, named in config.yaml, or both. A device only in
    config.yaml (``seen: false``) has no address, host name or times yet."""

    mac: str | None
    ip: IPv4Address | None
    name: str | None
    hostname: str | None
    policy: str | None
    seen: bool
    first_seen: datetime | None
    last_seen: datetime | None


class DevicePolicyUpdate(BaseModel):
    """``PUT /devices/{mac or ip}``: the policy, and optionally a new name."""

    policy: DevicePolicy
    name: str | None = Field(default=None, min_length=1, max_length=64)


class DevicePolicyView(BaseModel):
    """The device entry of config.yaml after a policy change."""

    name: str
    mac: str | None
    ip: IPv4Address | None
    policy: str


class UplinkStatus(BaseModel):
    """One uplink as core sees it now."""

    name: str
    enabled: bool
    in_use: bool  # routing.mode full through it, or a device policy
    gateway_alive: bool | None  # None: not watched, or not probed yet
    checked_at: datetime | None
    error: str
    gateway_route: bool | None  # None: the route table could not be read
    kill_switch_route: bool | None
    lan_access: bool | None  # upstreams.vps.lan_access; None for an uplink without the setting


class DpnStatus(BaseModel):
    """The Mysterium consumer of uplink dpn as core last saw it."""

    identity: str | None
    registration: str
    connection: str
    country: str | None
    error: str
    balance_wei: str  # MYST in wei (18 decimals)
    channel_address: str  # top-up address: MYST on Polygon


class BoxStatus(BaseModel):
    """The LAN router at a glance: what config.yaml asks and what the host does."""

    mode: str
    default_upstream: str
    failopen: bool
    rules_current: bool | None
    # routing.mode full, its uplink does not answer and failopen is false: the LAN has no exit.
    lan_without_exit: bool
    uplinks: list[UplinkStatus]
    dpn: DpnStatus | None = None  # None: uplink dpn is off, or core has not asked the consumer yet


class RoutingUpdate(BaseModel):
    """A change of routing; at least one field. ``smart`` is not switchable yet (Stage 10)."""

    mode: Literal["off", "full"] | None = None
    default_upstream: Upstream | None = None


class RoutingView(BaseModel):
    mode: str
    default_upstream: str
    # applied: AdGuard follows the mode already; pending: it did not answer and catches up at the
    # next start of core; none: this box runs no AdGuard.
    adguard: Literal["applied", "pending", "none"]


class VpsLanAccessUpdate(BaseModel):
    allowed: bool


class VpsLanAccessView(BaseModel):
    allowed: bool


class DpnCountry(BaseModel):
    """Nodes of one country for uplink dpn; prices in wei of MYST (18 decimals)."""

    country: str
    nodes: int
    min_per_hour_wei: str
    min_per_gib_wei: str


class DpnCountryUpdate(BaseModel):
    country: str | None  # None: any country


class DpnCountryView(BaseModel):
    country: str | None
