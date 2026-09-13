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
    """A LAN device the box has seen, with the name and policy config.yaml gives it."""

    mac: str
    ip: IPv4Address
    name: str | None
    hostname: str | None
    policy: str | None
    first_seen: datetime
    last_seen: datetime


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


class BoxStatus(BaseModel):
    """The LAN router at a glance: what config.yaml asks and what the host does."""

    mode: str
    default_upstream: str
    failopen: bool
    rules_current: bool | None
    # routing.mode full, its uplink does not answer and failopen is false: the LAN has no exit.
    lan_without_exit: bool
    uplinks: list[UplinkStatus]


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
