"""Bodies of the core API that the CLI reads back: one definition for both sides."""

from datetime import datetime
from ipaddress import IPv4Address
from typing import Literal

from pydantic import BaseModel, Field

from vibedpn.config import DevicePolicy


class PeerCreate(BaseModel):
    name: str
    tunnel_only: bool = False


class PeerTraffic(BaseModel):
    """How much one peer has used over the period asked for, kept across restarts of the tunnel."""

    name: str  # empty when the peer is gone but its totals are still kept
    public_key: str
    rx_bytes: int
    tx_bytes: int


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
    # The consumers of the exit countries of domain rules (decision 20), by country.
    dpn_countries: list[DpnStatus] = []


class RoutingUpdate(BaseModel):
    """A change of routing; at least one field."""

    mode: Literal["off", "full", "smart"] | None = None
    # An uplink key: vps, dpn, or wg-<name>; the box refuses one it does not run.
    default_upstream: str | None = None


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


class HostInterface(BaseModel):
    """An interface of the host with a global IPv4 address."""

    name: str
    address: str
    prefixlen: int
    default_route: bool  # the WAN of gateway mode, the only port of sidecar mode


class NetworkView(BaseModel):
    """The network config.yaml holds, and whether the box still runs an older one."""

    mode: str
    lan_interface: str
    lan_address: str
    wan_interface: str | None
    restart_required: bool
    interfaces: list[HostInterface]


class NetworkUpdate(BaseModel):
    lan_interface: str | None  # None: sidecar on the default-route interface


class DomainRuleUpdate(BaseModel):
    """The channel of a site in routing.mode smart; the domain comes from the path."""

    via: Literal["vps", "dpn", "wg", "tor", "xray", "direct"]
    country: str | None = None
    uplink: str | None = None  # via wg: the name of the exit in upstreams.wg
    learn: bool = True
    also: list[str] = []


class DomainRuleView(BaseModel):
    domain: str
    via: str
    country: str | None
    uplink: str | None
    learn: bool
    also: list[str]


class NetworkRuleUpdate(BaseModel):
    """A network of addresses and its channel in routing.mode smart."""

    network: str
    via: Literal["vps", "dpn", "wg", "tor", "xray", "direct"]
    country: str | None = None
    uplink: str | None = None


class NetworkRuleView(BaseModel):
    network: str
    via: str
    country: str | None
    uplink: str | None


class DomainListUpdate(BaseModel):
    """A ready domain list by URL and the channel of all its domains."""

    url: str
    via: Literal["vps", "dpn", "wg", "tor", "xray", "direct"]
    country: str | None = None
    uplink: str | None = None  # via wg: the name of the exit in upstreams.wg


class DomainListView(BaseModel):
    url: str
    via: str
    country: str | None
    uplink: str | None
    domains: int  # 0 until core has a first copy
    fetched_at: float | None  # unix seconds of the copy in use
    error: str  # why the copy in use is not newer, or why there is none


class JournalEntryView(BaseModel):
    """One DNS query of a device, as the sniffer shows it."""

    time: float
    name: str
    qtype: str
    cached: bool
    addresses: list[str]
    channel: str  # smart_* set of the rule it went through, or "direct"
    learned_from: str | None  # this query taught the name to follow that site


class JournalDeviceView(BaseModel):
    client: str
    queries: int


class LearnedView(BaseModel):
    name: str
    parent: str
    source: str  # time | cname
    first_seen: float
    last_seen: float
    hits: int


class EventView(BaseModel):
    """One entry of the event journal: codes and numbers, the phrase is built by the reader."""

    time: float  # unix seconds
    kind: str  # wifi | uplink
    subject: str  # a client MAC or the interface for wifi, an uplink key for uplink
    name: str | None  # the device name of a client MAC; None when the box knows none
    action: str  # engine/events.py: EventAction
    detail: dict[str, int | float | str]


class WifiClientView(BaseModel):
    """A client connected to the access point now, as hostapd reports it."""

    mac: str
    name: str | None  # the host name discovery knows for this MAC
    connected_seconds: int
    signal_dbm: int | None
    inactive_ms: int | None
    rx_bytes: int | None
    tx_bytes: int | None


class WgUplinkCreate(BaseModel):
    """``POST /uplinks/wg``: a name and the text of a provider's WireGuard file."""

    name: str
    config: str = Field(max_length=64 * 1024)


class WgUplinkView(BaseModel):
    """A named WireGuard exit; its file is never sent back, only whether it is there."""

    name: str
    enabled: bool
    has_file: bool


class ApplyView(BaseModel):
    """The last change the host applied for the panel (engine/apply.py)."""

    pending: bool  # the host has not run `vibedpn up` for the last change yet
    ok: bool | None  # None: nothing applied yet
    message: str
    finished_at: float | None


class TorUplinkUpdate(BaseModel):
    """``PUT /uplinks/tor``: turn the exit through Tor on or off."""

    enabled: bool


class TorUplinkView(BaseModel):
    """Uplink tor as the panel shows it; a bridge is given as its transport and address only."""

    enabled: bool
    bridges: list[str]  # "snowflake 192.0.2.3:80"
    apply: ApplyView


class WgUplinksView(BaseModel):
    uplinks: list[WgUplinkView]
    apply: ApplyView
