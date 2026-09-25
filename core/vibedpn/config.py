"""Model of ``config.yaml``: the single source of truth of a VibeDPN box.

The whole v1 schema is declared here so that later stages extend one place. What a ``home``,
``vps`` or ``client`` box must and must not contain is enforced by ``Config`` itself; the
Compose profile preset of a role is derived by :meth:`Config.compose_profiles` and written to
``.env`` by ``vibedpn init``. The human-readable spec of this format, with an example per
role, is ``docs/manuals/configSpec.md``; keep the two in sync.
"""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

# Protocol-level constants (not user settings): validation patterns and port bounds.
MAC_PATTERN = re.compile(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$")
COUNTRY_PATTERN = re.compile(r"^[A-Z]{2}$")
PORT_RANGE_PATTERN = re.compile(r"^(\d{1,5})-(\d{1,5})$")
DOMAIN_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$"
)
DEFAULT_UI_HOST_NAME = "vibedpn.lan"
# The panel language unless a browser chose another; a locales/<code>.json file of the box.
DEFAULT_UI_LANGUAGE = "ru"
LANGUAGE_PATTERN = re.compile(r"^[a-z]{2}$")
# Postgres of the panel on a lite box (docs/uiVariants.md); a full box keeps the Postgres defaults.
LITE_DB_SHARED_BUFFERS = "32MB"
LITE_DB_MAX_CONNECTIONS = 20
DOH_URL_PATTERN = re.compile(r"^https://[^\s/]+/\S*$")
LIST_URL_PATTERN = re.compile(r"^https?://[^\s/]+(/\S*)?$")
HOSTNAME_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$"
)
INTERFACE_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,15}$")  # IFNAMSIZ is 16 with the NUL
# A named WireGuard uplink: the name becomes secrets/wg-<name>.conf, the Compose service
# wg-<name> and the routing key wg-<name>, so it stays within what all three accept.
WG_UPLINK_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,23}$")
WG_KEY_PREFIX = "wg-"
# Fingerprints of config.yaml sections in .env, one per service that reads at start what those
# sections become (Config.config_digests). Short: they only have to change when the sections do.
DIGEST_CORE = "VIBEDPN_DIGEST_CORE"
DIGEST_HOSTAPD = "VIBEDPN_DIGEST_HOSTAPD"
DIGEST_DNSMASQ = "VIBEDPN_DIGEST_DNSMASQ"
DIGEST_ADGUARD = "VIBEDPN_DIGEST_ADGUARD"
DIGEST_WG_SERVER = "VIBEDPN_DIGEST_WG_SERVER"
DIGEST_ACCESS = "VIBEDPN_DIGEST_ACCESS"
DIGEST_TOR = "VIBEDPN_DIGEST_TOR"
DIGEST_SERVICES = {
    DIGEST_CORE: "core",
    DIGEST_HOSTAPD: "hostapd",
    DIGEST_DNSMASQ: "dnsmasq",
    DIGEST_ADGUARD: "adguard",
    DIGEST_WG_SERVER: "wg-server",
    DIGEST_ACCESS: "access",
    DIGEST_TOR: "tor",
}
DIGEST_LENGTH = 16


def config_digest(payload: object) -> str:
    """A stable fingerprint of JSON-like data: the same sections give the same value on any box."""
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:DIGEST_LENGTH]


def recreated_services(previous: dict[str, str], current: dict[str, str]) -> list[str]:
    """The services ``up`` recreates because their sections of config.yaml changed: a fingerprint
    that was in the previous .env and differs now. A first start has nothing to compare with."""
    return [
        DIGEST_SERVICES[name]
        for name, value in current.items()
        if name in DIGEST_SERVICES and previous.get(name) not in (None, value)
    ]


PORT_MIN = 1
PORT_MAX = 65535
DEFAULT_SSH_PORT = 22
MIN_WG_SUBNET_ADDRESSES = 4  # network, server, at least one peer, broadcast
# REALITY off 443 gets a warning from Xray itself: a TLS server on another port stands out.
DEFAULT_ACCESS_PORT = 443
# The site REALITY borrows its handshake from. Not every TLS 1.3 site works: www.microsoft.com
# never completes one, dl.google.com always does (knowledge xray/realityServer.md).
DEFAULT_ACCESS_TARGET = "dl.google.com"
LAST_PREFIX_WITH_BROADCAST = 30  # /31 and /32 have no reserved network/broadcast addresses
# The Telegram bot: an exit or the access point silent this long is worth a message. The uplink
# watcher probes every 5 s, so a shorter threshold would report every flap.
DEFAULT_ALERT_AFTER_SECONDS = 60
MIN_ALERT_AFTER_SECONDS = 15
MAX_ALERT_AFTER_SECONDS = 24 * 3600
DEFAULT_TELEGRAM_TIMEZONE = "Europe/Moscow"
DEFAULT_REPORT_HOUR = 10
LAST_HOUR = 23
# Default DHCP pool of gateway mode: hosts from this offset up to this many before the last one
# (a /24 hands out .100-.249), leaving the low addresses to the box and static devices.
DHCP_POOL_FIRST_OFFSET = 100
DHCP_POOL_LAST_MARGIN = 5
MIN_DHCP_SUBNET_PREFIX = 28
LEASE_PATTERN = re.compile(r"^(\d+[mhdw]?|infinite)$")

Port = Annotated[int, Field(ge=PORT_MIN, le=PORT_MAX)]
InterfaceName = Annotated[str, Field(pattern=INTERFACE_PATTERN.pattern)]


class Role(StrEnum):
    HOME = "home"
    VPS = "vps"
    CLIENT = "client"


class Profile(StrEnum):
    """Compose profiles, in the order they are listed in ``COMPOSE_PROFILES``."""

    PROVIDER = "provider"
    CONSUMER = "consumer"
    WG_SERVER = "wg-server"
    WG_CLIENT = "wg-client"
    WG_UPLINK = "wg-uplink"  # the named uplinks of upstreams.wg, generated from compose.yaml
    TOR = "tor"  # uplink tor: a gateway into Tor through bridges (decision 27)
    XRAY = "xray"  # uplink xray: a masking transport by the owner's share link (decision 29)
    ROUTER = "router"
    DHCP = "dhcp"  # dnsmasq: gateway mode only, never next to the DHCP of an ISP router
    WIFI = "wifi"  # hostapd: gateway mode with network.wifi, the LAN interface is the radio
    DNS = "dns"
    UI = "ui"
    ACCESS = "access"  # the access server: VLESS/REALITY for the owner's people (decision 30)


class NetworkMode(StrEnum):
    SIDECAR = "sidecar"
    GATEWAY = "gateway"


class RoutingMode(StrEnum):
    OFF = "off"
    FULL = "full"
    SMART = "smart"


class Upstream(StrEnum):
    VPS = "vps"
    DPN = "dpn"
    TOR = "tor"
    XRAY = "xray"  # a masking transport where plain WireGuard does not pass (decision 29)


class DevicePolicy(StrEnum):
    VPS = "vps"
    DPN = "dpn"
    TOR = "tor"
    XRAY = "xray"
    BYPASS = "bypass"
    BLOCK = "block"


class Traversal(StrEnum):
    """NAT traversal methods of the Mysterium node, tried in the listed order."""

    MANUAL = "manual"
    UPNP = "upnp"
    HOLEPUNCHING = "holepunching"


DEFAULT_TRAVERSAL = (Traversal.MANUAL, Traversal.UPNP, Traversal.HOLEPUNCHING)


class StrictModel(BaseModel):
    """Base of every section: unknown keys are errors, strings are stripped."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def parse_port_range(value: str) -> tuple[int, int]:
    """Parse ``"start-end"`` into a tuple; raise ``ValueError`` on anything else."""
    match = PORT_RANGE_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError(f"{value!r} is not a port range (expected 'start-end')")
    start, end = int(match[1]), int(match[2])
    if not PORT_MIN <= start <= end <= PORT_MAX:
        raise ValueError(f"{value!r}: ports must be within {PORT_MIN}-{PORT_MAX} and start <= end")
    return start, end


def normalize_mac(value: str) -> str:
    """Lower-case a MAC and accept ``-`` as separator; raise ``ValueError`` if not a MAC."""
    mac = value.lower().replace("-", ":")
    if MAC_PATTERN.fullmatch(mac) is None:
        raise ValueError(f"{value!r} is not a MAC address (expected aa:bb:cc:dd:ee:ff)")
    return mac


def check_endpoint(value: str) -> str:
    """A hostname or IPv4 address; raise ``ValueError`` with a user-facing reason otherwise."""
    try:
        IPv4Address(value)
    except ValueError:
        looks_numeric = value.replace(".", "").isdigit()
        if looks_numeric or HOSTNAME_PATTERN.fullmatch(value) is None:
            raise ValueError(f"{value!r} is not a hostname or IPv4 address") from None
    return value


def normalize_country(value: object) -> str:
    """Upper-case an ISO 3166-1 alpha-2 code; raise ``ValueError`` if it is not one."""
    if not isinstance(value, str):
        raise ValueError(f"{value!r} is not a country code")
    code = value.strip().upper()
    if COUNTRY_PATTERN.fullmatch(code) is None:
        raise ValueError(f"{value!r} is not an ISO 3166-1 alpha-2 country code")
    return code


def normalize_domain(value: str) -> str:
    """Lower-case a domain suffix, strip surrounding dots; raise ``ValueError`` if invalid."""
    domain = value.lower().strip(".")
    if DOMAIN_PATTERN.fullmatch(domain) is None:
        raise ValueError(f"{value!r} is not a domain name")
    return domain


class WifiBand(StrEnum):
    BAND_2_4 = "2.4"
    BAND_5 = "5"


class WifiSecurity(StrEnum):
    WPA2_WPA3 = "wpa2-wpa3"  # transition: devices without SAE still join (decision 10)
    WPA3 = "wpa3"


# Channels a band may carry; what a country allows is checked by the radio itself (country_code).
WIFI_CHANNELS = {
    WifiBand.BAND_2_4: range(1, 14),
    WifiBand.BAND_5: range(36, 166),
}
SSID_MAX_BYTES = 32
# The Snowflake bridges of Tor Browser, taken 2026-09-17 from tor-browser-build,
# projects/tor-expert-bundle/pt_config.json (https://gitlab.torproject.org/tpo/applications/
# tor-browser-build/-/raw/main/projects/tor-expert-bundle/pt_config.json). They change with Tor
# Browser releases; the owner overrides upstreams.tor.bridges.
_SNOWFLAKE_ICE = (
    "ice=stun:stun.epygi.com:3478,stun:stun.uls.co.za:3478,stun:stun.voipgate.com:3478,"
    "stun:stun.mixvoip.com:3478,stun:stun.telnyx.com:3478,stun:stun.hot-chilli.net:3478,"
    "stun:stun.fitauto.ru:3478,stun:stun.m-online.net:3478"
)
_SNOWFLAKE_TAIL = (
    "url=https://1098762253.rsc.cdn77.org/ fronts=app.datapacket.com,www.datapacket.com "
    f"{_SNOWFLAKE_ICE} utls-imitate=hellorandomizedalpn"
)
DEFAULT_TOR_BRIDGES = (
    "snowflake 192.0.2.3:80 2B280B23E1107BB62ABFC40DDCC8824814F80A72"
    f" fingerprint=2B280B23E1107BB62ABFC40DDCC8824814F80A72 {_SNOWFLAKE_TAIL}",
    "snowflake 192.0.2.4:80 8838024498816A039FCBBAB14E6F40A0843051FA"
    f" fingerprint=8838024498816A039FCBBAB14E6F40A0843051FA {_SNOWFLAKE_TAIL}",
)
# Transports images/tor has a client for: snowflake-client, and obfs4proxy for obfs4 and meek_lite.
TOR_TRANSPORTS = frozenset({"snowflake", "obfs4", "meek_lite"})
MIN_BRIDGE_WORDS = 2  # the transport and the address; the rest are transport arguments
MAX_RULE_COUNTRIES = 8  # engine/router.py MAX_COUNTRIES: one consumer per country


class WifiConfig(StrictModel):
    """The access point of gateway mode on the LAN interface; the passphrase is a secret."""

    ssid: str
    country: str
    band: WifiBand = WifiBand.BAND_2_4
    channel: int = 6
    security: WifiSecurity = WifiSecurity.WPA2_WPA3

    @field_validator("ssid")
    @classmethod
    def check_ssid(cls, value: str) -> str:
        if not value or len(value.encode("utf-8")) > SSID_MAX_BYTES or "\n" in value:
            raise ValueError(f"{value!r} is not an SSID (1 to {SSID_MAX_BYTES} bytes, one line)")
        return value

    @field_validator("country", mode="before")
    @classmethod
    def check_country(cls, value: object) -> str:
        return normalize_country(value)

    @model_validator(mode="after")
    def check_channel(self) -> Self:
        if self.channel not in WIFI_CHANNELS[self.band]:
            allowed = WIFI_CHANNELS[self.band]
            raise ValueError(
                f"channel {self.channel} is not in band {self.band.value} GHz"
                f" ({allowed.start}-{allowed.stop - 1})"
            )
        return self


class DhcpConfig(StrictModel):
    """DHCP of gateway mode (dnsmasq on the LAN side); empty bounds take the default pool."""

    range_start: IPv4Address | None = None
    range_end: IPv4Address | None = None
    lease: str = "12h"

    @field_validator("lease")
    @classmethod
    def check_lease(cls, value: str) -> str:
        if LEASE_PATTERN.fullmatch(value) is None:
            raise ValueError(f"{value!r} is not a lease time (like 45m, 12h, 2d or infinite)")
        return value


class NetworkConfig(StrictModel):
    """Where the box sits: one LAN port (sidecar) or WAN+LAN (gateway, Stage 9)."""

    mode: NetworkMode = NetworkMode.SIDECAR
    lan_interface: InterfaceName
    lan_subnet: IPv4Network
    lan_address: IPv4Address
    wan_interface: InterfaceName | None = None
    dhcp: DhcpConfig | None = None
    wifi: WifiConfig | None = None

    def dhcp_pool(self) -> tuple[IPv4Address, IPv4Address]:
        """The addresses dnsmasq hands out: the configured bounds or the default pool."""
        subnet = self.lan_subnet
        first = subnet.network_address + 1
        last = subnet.broadcast_address - 1
        size = int(last) - int(first) + 1
        dhcp = self.dhcp or DhcpConfig()
        start = dhcp.range_start or first + min(DHCP_POOL_FIRST_OFFSET - 1, size // 2)
        end = dhcp.range_end or last - min(DHCP_POOL_LAST_MARGIN, size // 4)
        return start, end

    @model_validator(mode="after")
    def check_wifi(self) -> Self:
        if self.wifi is not None and self.mode is not NetworkMode.GATEWAY:
            raise ValueError("network.wifi is only used with network.mode 'gateway'")
        return self

    @model_validator(mode="after")
    def check_dhcp(self) -> Self:
        if self.dhcp is not None and self.mode is not NetworkMode.GATEWAY:
            raise ValueError("network.dhcp is only used with network.mode 'gateway'")
        if self.mode is not NetworkMode.GATEWAY:
            return self
        if self.lan_subnet.prefixlen > MIN_DHCP_SUBNET_PREFIX:
            raise ValueError(
                f"network.lan_subnet {self.lan_subnet} is too small for DHCP in gateway mode"
                f" (at most /{MIN_DHCP_SUBNET_PREFIX})"
            )
        start, end = self.dhcp_pool()
        hosts = (self.lan_subnet.network_address + 1, self.lan_subnet.broadcast_address - 1)
        if not (hosts[0] <= start <= end <= hosts[1]):
            raise ValueError(
                f"network.dhcp range {start}-{end} is not an ordered range of host addresses"
                f" of network.lan_subnet {self.lan_subnet}"
            )
        if start <= self.lan_address <= end:
            raise ValueError(
                f"network.lan_address {self.lan_address} lies inside the DHCP range {start}-{end}"
            )
        return self

    @model_validator(mode="after")
    def check_lan_address(self) -> Self:
        subnet = self.lan_subnet
        reserved = (
            (subnet.network_address, subnet.broadcast_address)
            if subnet.prefixlen <= LAST_PREFIX_WITH_BROADCAST
            else ()
        )
        if self.lan_address not in subnet or self.lan_address in reserved:
            raise ValueError(
                f"network.lan_address {self.lan_address} is not a host address of"
                f" network.lan_subnet {subnet}"
            )
        return self

    @model_validator(mode="after")
    def check_interfaces(self) -> Self:
        if self.mode is NetworkMode.GATEWAY and self.wan_interface is None:
            raise ValueError("network.mode 'gateway' requires network.wan_interface")
        if self.mode is NetworkMode.SIDECAR and self.wan_interface is not None:
            raise ValueError("network.wan_interface is only used with network.mode 'gateway'")
        if self.wan_interface == self.lan_interface:
            raise ValueError("network.wan_interface must differ from network.lan_interface")
        return self


class DomainVia(StrEnum):
    """Where a domain of routing.domains goes in routing.mode smart."""

    VPS = "vps"
    DPN = "dpn"
    WG = "wg"  # a named WireGuard exit of upstreams.wg, named by `uplink`
    TOR = "tor"
    XRAY = "xray"
    DIRECT = "direct"


class DomainChannel(StrictModel):
    """Where the names of a site or of a whole list go in smart: an uplink, Mysterium in a country,
    a named WireGuard exit, or direct. Sets, marks, uplinks and country consumers are built from
    channels."""

    via: DomainVia
    country: str | None = None  # via dpn: the exit country; None: any
    uplink: str | None = None  # via wg: the name of the exit in upstreams.wg

    @field_validator("country", mode="before")
    @classmethod
    def check_country(cls, value: object) -> str | None:
        return None if value is None else normalize_country(value)

    @field_validator("uplink")
    @classmethod
    def check_uplink(cls, value: str | None) -> str | None:
        if value is not None and not WG_UPLINK_NAME.fullmatch(value):
            raise ValueError(f"{value!r} is not a name of upstreams.wg")
        return value

    def subject(self) -> str:
        """What the owner calls this entry in a message."""
        raise NotImplementedError

    @model_validator(mode="after")
    def check_country_channel(self) -> Self:
        if self.country is not None and self.via is not DomainVia.DPN:
            raise ValueError(f"{self.subject()}: a country is only chosen for via dpn")
        if self.via is DomainVia.WG and self.uplink is None:
            raise ValueError(f"{self.subject()}: via wg names its exit in uplink")
        if self.uplink is not None and self.via is not DomainVia.WG:
            raise ValueError(f"{self.subject()}: an uplink is only named for via wg")
        return self


class DomainRule(DomainChannel):
    """One site of the smart mode (docs/decisions.md, 11): the domain with its subdomains, the
    channel, and the CDNs that follow it. ``also`` holds the ones the owner pinned; the ones core
    learned live in its own store, not in config.yaml."""

    domain: str
    learn: bool = True  # CDNs asked by a device right after this site follow it automatically
    also: list[str] = Field(default_factory=list)

    @field_validator("domain")
    @classmethod
    def check_domain(cls, value: str) -> str:
        return normalize_domain(value)

    @field_validator("also")
    @classmethod
    def check_also(cls, values: list[str]) -> list[str]:
        return [normalize_domain(value) for value in values]

    def subject(self) -> str:
        return self.domain

    def names(self) -> list[str]:
        return [self.domain, *self.also]


class DomainList(DomainChannel):
    """A ready list of sites by URL (docs/decisions.md, 21): every domain of it takes the channel of
    the list; a rule of routing.domains for the same name wins. Core fetches and caches it."""

    url: str

    @field_validator("url")
    @classmethod
    def check_url(cls, value: str) -> str:
        if LIST_URL_PATTERN.fullmatch(value) is None:
            raise ValueError(f"{value!r} is not an http(s) URL of a domain list")
        return value

    def subject(self) -> str:
        return self.url


class NetworkRule(DomainChannel):
    """A network of addresses in routing.mode smart (docs/decisions.md, 28): for a service an app
    reaches by address rather than by name — the data centers of Telegram. Matched by destination
    address, so nothing is resolved and nothing is learned."""

    network: IPv4Network

    @field_validator("network", mode="before")
    @classmethod
    def check_network(cls, value: object) -> IPv4Network:
        try:
            return IPv4Network(str(value).strip())
        except ValueError:
            raise ValueError(
                f"routing.networks: {value!r} is not an IPv4 network (a.b.c.d/nn, host bits zero)"
            ) from None

    def subject(self) -> str:
        return str(self.network)


def uplink_key(value: str, field: str) -> str:
    """An uplink key the owner may name: a fixed uplink or wg-<name> of upstreams.wg

    The consumers of rule countries (dpn-<cc>) are not in it: they serve their rules only
    Whether the uplink is enabled is checked against upstreams, by the box
    """
    if value.startswith(WG_KEY_PREFIX):
        if not WG_UPLINK_NAME.fullmatch(value.removeprefix(WG_KEY_PREFIX)):
            raise ValueError(
                f"{field}: {value!r} names no usable uplink "
                "(lowercase letters, digits and '-' after 'wg-')"
            )
        return value
    try:
        return Upstream(value).value
    except ValueError:
        raise ValueError(
            f"{field}: {value!r} is not an uplink"
            " (vps, dpn, tor, xray, or wg-<name> of upstreams.wg)"
        ) from None


class RoutingConfig(StrictModel):
    """LAN traffic policy: everything direct, everything via an uplink, or by domain rules."""

    mode: RoutingMode = RoutingMode.OFF
    # An uplink key: `vps`, `dpn`, or `wg-<name>` of upstreams.wg (decision 23). Not an enum:
    # the named uplinks are the owner's, and their keys are known only from the configuration.
    default_upstream: str
    failopen: bool = False
    # Uplink keys in order (decision 32): the traffic of a silent uplink goes through the first one
    # that answers; failopen decides only once none of them does.
    fallback: list[str] = Field(default_factory=list)
    domains: list[DomainRule] = Field(default_factory=list)
    lists: list[DomainList] = Field(default_factory=list)
    networks: list[NetworkRule] = Field(default_factory=list)

    def channels(self) -> list[DomainChannel]:
        """Every channel the rules, the lists and the networks name: what sets, marks and uplinks
        follow."""
        return [*self.domains, *self.lists, *self.networks]

    @field_validator("networks")
    @classmethod
    def check_unique_networks(cls, value: list[NetworkRule]) -> list[NetworkRule]:
        seen: set[IPv4Network] = set()
        for rule in value:
            if rule.network in seen:
                raise ValueError(f"routing.networks: {rule.network} is listed twice")
            seen.add(rule.network)
        return value

    @field_validator("default_upstream")
    @classmethod
    def check_default_upstream(cls, value: str) -> str:
        """A key of an uplink; whether that uplink is enabled is checked against upstreams."""
        return uplink_key(value, "routing.default_upstream")

    @field_validator("fallback")
    @classmethod
    def check_fallback(cls, value: list[str]) -> list[str]:
        keys = [uplink_key(key, "routing.fallback") for key in value]
        repeated = sorted({key for key in keys if keys.count(key) > 1})
        if repeated:
            raise ValueError(f"routing.fallback names an uplink twice: {', '.join(repeated)}")
        return keys

    @model_validator(mode="before")
    @classmethod
    def migrate_smart_domains(cls, data: object) -> object:
        """Before Stage 10 the smart list was plain suffixes through default_upstream."""
        if not isinstance(data, dict) or "smart_domains" not in data:
            return data
        if "domains" in data:
            raise ValueError("routing: use domains; smart_domains is the old form of the same list")
        migrated = dict(data)
        suffixes = migrated.pop("smart_domains") or []
        via = migrated.get("default_upstream")
        migrated["domains"] = [{"domain": suffix, "via": via} for suffix in suffixes]
        return migrated

    @model_validator(mode="after")
    def check_unique_names(self) -> Self:
        names = [name for rule in self.domains for name in rule.names()]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"routing.domains names a domain twice: {', '.join(duplicates)}")
        urls = [item.url for item in self.lists]
        repeated = sorted({url for url in urls if urls.count(url) > 1})
        if repeated:
            raise ValueError(f"routing.lists names a URL twice: {', '.join(repeated)}")
        return self


class DeviceConfig(StrictModel):
    """A LAN device with its own policy; identified by MAC, IP is the fallback."""

    name: str = Field(min_length=1, max_length=64)
    mac: str | None = None
    ip: IPv4Address | None = None
    policy: DevicePolicy

    @field_validator("mac")
    @classmethod
    def check_mac(cls, value: str | None) -> str | None:
        return None if value is None else normalize_mac(value)

    @model_validator(mode="after")
    def check_identity(self) -> Self:
        if self.mac is None and self.ip is None:
            raise ValueError(f"device {self.name!r} needs a mac or an ip")
        return self


class VpsUplink(StrictModel):
    """Private WireGuard tunnel to the owner's VPS (``wg-client`` container).

    The peer configuration is not referenced here: ``vibedpn init --peer-config`` stores it as
    ``secrets/wg-client.conf``, the fixed path ``compose.yaml`` mounts into ``wg-client``.
    """

    enabled: bool = False
    # Whether LAN devices whose traffic goes through the tunnel reach private addresses behind it:
    # the node panel and the core API on the tunnel address of the VPS. Closed unless the owner
    # opens it (decision of the owner, 2026-09-13).
    lan_access: bool = False


class DpnUplink(StrictModel):
    """Mysterium consumer: exit through a network node, optionally pinned to a country."""

    enabled: bool = False
    country: str | None = None

    @field_validator("country", mode="before")
    @classmethod
    def check_country(cls, value: object) -> str | None:
        return None if value is None else normalize_country(value)


class WgUplink(StrictModel):
    """An exit through a ready WireGuard configuration file, named by the owner.

    The box does not know whose file it is: a free Proton account, a paid provider, another box —
    all of them are this uplink. The file is not referenced here either: it is
    ``secrets/wg-<name>.conf``, the path the generated Compose service mounts (decision 23).
    """

    enabled: bool = True


class TorUplink(StrictModel):
    """An exit through Tor: free, no account, no registration, TCP only (decision 27).

    A network that blocks Tor is reached through bridges, one line of a bridge per entry, exactly as
    Tor writes them after ``Bridge``. The default is the Snowflake bridges Tor Browser ships: from a
    Russian ISP Snowflake reached Tor where the built-in obfs4 bridges did not (knowledge
    tor/snowflake.md). Core writes the lines to ``data/tor/bridges`` for the gateway container.
    """

    enabled: bool = False
    bridges: list[str] = Field(default_factory=lambda: list(DEFAULT_TOR_BRIDGES))

    @field_validator("bridges")
    @classmethod
    def check_bridges(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("upstreams.tor.bridges needs at least one bridge line")
        lines = [raw.strip() for raw in value]
        for line in lines:
            words = line.split()
            if "\n" in line or len(words) < MIN_BRIDGE_WORDS or words[0] not in TOR_TRANSPORTS:
                raise ValueError(
                    f"upstreams.tor.bridges: {line[:60]!r} is not a bridge line"
                    f" ('<transport> <address:port> ...', transport one of"
                    f" {', '.join(sorted(TOR_TRANSPORTS))})"
                )
        return lines

    def has_custom_bridges(self) -> bool:
        """Whether the owner set bridges of their own; the default list is not written back."""
        return self.bridges != list(DEFAULT_TOR_BRIDGES)


class XrayUplink(StrictModel):
    """An exit through a masking transport: VLESS over Reality and the rest Xray speaks.

    The share link of the server carries the credentials, so it lives in ``secrets/xray-link`` and
    not here — `vibedpn xray enable <link>` puts it there. Core renders the configuration of the
    gateway from it at every ``up`` (engine/xray.py).
    """

    enabled: bool = False


class UpstreamsConfig(StrictModel):
    vps: VpsUplink = Field(default_factory=VpsUplink)
    dpn: DpnUplink = Field(default_factory=DpnUplink)
    tor: TorUplink = Field(default_factory=TorUplink)
    xray: XrayUplink = Field(default_factory=XrayUplink)
    # name -> its uplink; the name reaches a file name, a Compose service and a routing key
    wg: dict[str, WgUplink] = Field(default_factory=dict)

    @field_validator("wg")
    @classmethod
    def check_names(cls, value: dict[str, WgUplink]) -> dict[str, WgUplink]:
        for name in value:
            if not WG_UPLINK_NAME.fullmatch(name):
                raise ValueError(
                    f"upstreams.wg: {name!r} is not a usable name "
                    "(lowercase letters, digits and '-', up to 24 characters)"
                )
        return value

    def is_enabled(self, upstream: Upstream) -> bool:
        return {
            Upstream.VPS: self.vps.enabled,
            Upstream.DPN: self.dpn.enabled,
            Upstream.TOR: self.tor.enabled,
            Upstream.XRAY: self.xray.enabled,
        }[upstream]

    def is_key_enabled(self, key: str) -> bool:
        """Whether the uplink of a routing key is enabled: ``vps``, ``dpn``, ``dpn-<cc>`` (the
        country consumers of uplink dpn) or ``wg-<name>``."""
        if key.startswith(WG_KEY_PREFIX):
            uplink = self.wg.get(key.removeprefix(WG_KEY_PREFIX))
            return uplink is not None and uplink.enabled
        if key.startswith(Upstream.DPN.value):
            return self.is_enabled(Upstream.DPN)
        return self.is_enabled(Upstream(key))


class ProviderConfig(StrictModel):
    """Mysterium provider node: share bandwidth, earn MYST."""

    enabled: bool = False
    udp_ports: str = "56000-56100"
    traversal: list[Traversal] = Field(default_factory=lambda: list(DEFAULT_TRAVERSAL))

    @field_validator("udp_ports")
    @classmethod
    def check_udp_ports(cls, value: str) -> str:
        parse_port_range(value)
        return value

    @field_validator("traversal")
    @classmethod
    def check_traversal(cls, value: list[Traversal]) -> list[Traversal]:
        if not value:
            raise ValueError("provider.traversal needs at least one method")
        if len(set(value)) != len(value):
            raise ValueError("provider.traversal lists a method twice")
        return value


class WgServerConfig(StrictModel):
    """WireGuard server of a VPS box; home boxes dial ``endpoint:listen_port``."""

    endpoint: str
    subnet: IPv4Network = IPv4Network("10.78.0.0/24")
    listen_port: Port = 51820

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        return check_endpoint(value)

    @property
    def address(self) -> IPv4Address:
        """The first host of its subnet: 10.78.0.0/24 → 10.78.0.1. One rule in one place —
        engine/wg.py builds the interface address from this and nothing computes it twice."""
        return next(self.subnet.hosts())

    @field_validator("subnet")
    @classmethod
    def check_subnet(cls, value: IPv4Network) -> IPv4Network:
        if value.num_addresses < MIN_WG_SUBNET_ADDRESSES:
            raise ValueError(f"wg_server.subnet {value} is too small for a server and a peer")
        return value


class DnsConfig(StrictModel):
    """AdGuard Home on port 53 of the LAN interface with DNS-over-HTTPS upstreams."""

    enabled: bool = True
    upstreams: list[str] = Field(default_factory=lambda: ["https://dns.cloudflare.com/dns-query"])
    web_port: Port = 3000

    @field_validator("upstreams")
    @classmethod
    def check_upstreams(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("dns.upstreams needs at least one DNS-over-HTTPS URL")
        for url in value:
            if DOH_URL_PATTERN.fullmatch(url) is None:
                raise ValueError(f"{url!r} is not a DNS-over-HTTPS URL (https://host/path)")
        return value


class UiVariant(StrEnum):
    """One code base, two builds of the panel (docs/uiVariants.md)."""

    FULL = "full"  # N100 and larger
    LITE = "lite"  # Raspberry Pi: no background workers, no socket backplane, a small Postgres


class UiConfig(StrictModel):
    """Web UI (the start0 app in ui/) on the LAN interface; it also proxies the core API."""

    enabled: bool = True
    port: Port = 80
    variant: UiVariant = UiVariant.FULL
    # The name devices open the panel by; AdGuard answers it with network.lan_address.
    host_name: str = DEFAULT_UI_HOST_NAME
    # ISO 639-1 code of data/ui/locales/<code>.json; English is built into the panel.
    language: str = DEFAULT_UI_LANGUAGE

    @field_validator("host_name")
    @classmethod
    def check_host_name(cls, value: str) -> str:
        return normalize_domain(value)

    @field_validator("language", mode="before")
    @classmethod
    def check_language(cls, value: object) -> str:
        code = str(value).strip().lower()
        if LANGUAGE_PATTERN.fullmatch(code) is None:
            raise ValueError(f"{value!r} is not a two-letter ISO 639-1 language code")
        return code


class ApiConfig(StrictModel):
    """Core API; binds loopback only and is reached through ``ui``."""

    port: Port = 4480


class FirewallConfig(StrictModel):
    """Host firewall of a VPS: nftables table ``inet vibedpn``, input policy drop.

    Open by default: ssh, the WireGuard server port, the node's UDP range, the wg0 tunnel;
    ``allow_tcp``/``allow_udp`` are for other services the owner runs on the same VPS.
    """

    enabled: bool = True
    ssh_ports: list[Port] = Field(default_factory=lambda: [DEFAULT_SSH_PORT])
    allow_tcp: list[Port] = Field(default_factory=list)
    allow_udp: list[Port] = Field(default_factory=list)

    @field_validator("ssh_ports", "allow_tcp", "allow_udp")
    @classmethod
    def check_unique(cls, value: list[int]) -> list[int]:
        if len(set(value)) != len(value):
            raise ValueError("a port is listed twice")
        return value

    @field_validator("ssh_ports")
    @classmethod
    def check_ssh_ports(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError(
                "firewall.ssh_ports must keep at least one port, or you lock yourself out"
            )
        return value


class AccessConfig(StrictModel):
    """The access server: VLESS over REALITY for the owner's people (docs/manuals/accessServer.md).

    Every role may run it. On a box with a LAN a person outside gets what a device at home gets —
    the mode, the rules, AdGuard; on a VPS they go straight out. ``address`` is what their links
    name: a DNS name that follows the box (``ddns``) or the public address of a VPS, and a VPS
    falls back to ``wg_server.endpoint``. ``target`` is the site REALITY borrows its handshake from.
    """

    enabled: bool = False
    address: str | None = None
    port: Port = DEFAULT_ACCESS_PORT
    target: str = DEFAULT_ACCESS_TARGET

    @field_validator("address")
    @classmethod
    def check_address(cls, value: str | None) -> str | None:
        return None if value is None else check_endpoint(value)

    @field_validator("target")
    @classmethod
    def check_target(cls, value: str) -> str:
        return normalize_domain(value)


class DdnsConfig(StrictModel):
    """A DNS name that follows a changing public address: core calls the owner's update URL from
    ``secrets/ddns-url`` every few minutes. The URL carries a token, so it is a secret and never
    part of this file."""

    enabled: bool = False


class Weekday(StrEnum):
    """The day of the weekly report, in the order of ``datetime.weekday()``."""

    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


class TelegramReport(StrictModel):
    """The weekly report of the Telegram bot: the day and the hour in ``telegram.timezone``."""

    enabled: bool = True
    weekday: Weekday = Weekday.MONDAY
    hour: int = Field(default=DEFAULT_REPORT_HOUR, ge=0, le=LAST_HOUR)


class TelegramConfig(StrictModel):
    """The Telegram bot of the box: alerts and a weekly report to the owner's chat
    (docs/manuals/telegramBot.md). The bot token and the linked chat live in
    ``secrets/telegram.json``, never here; ``vibedpn telegram set`` puts them there."""

    enabled: bool = False
    alert_after_seconds: int = Field(
        default=DEFAULT_ALERT_AFTER_SECONDS, ge=MIN_ALERT_AFTER_SECONDS, le=MAX_ALERT_AFTER_SECONDS
    )
    # The clock of every message and of the report: the box may stand in another zone than its
    # owner, and its own clock is not theirs to set.
    timezone: str = DEFAULT_TELEGRAM_TIMEZONE
    report: TelegramReport = Field(default_factory=TelegramReport)

    @field_validator("timezone")
    @classmethod
    def check_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(
                f"{value!r} is not a time zone of the tz database, such as Europe/Moscow"
            ) from None
        return value


# Sections that describe a LAN-side box and make no sense on a headless VPS.
# Sections a VPS has no use for. `ui` is not among them since Stage 11: a VPS may run the panel
# too, but only through the tunnel and only when the owner says so (see `_vps_panel_default`).
LAN_SECTIONS = ("network", "routing", "devices", "upstreams", "dns")
# Sections that only a VPS has (LAN roles get the router engine in Stage 4).
VPS_SECTIONS = ("firewall",)


class Config(StrictModel):
    """Top level of ``config.yaml``."""

    version: Literal[1]
    role: Role
    network: NetworkConfig | None = None
    routing: RoutingConfig | None = None
    devices: list[DeviceConfig] = Field(default_factory=list)
    upstreams: UpstreamsConfig = Field(default_factory=UpstreamsConfig)
    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    wg_server: WgServerConfig | None = None
    dns: DnsConfig = Field(default_factory=DnsConfig)
    ui: UiConfig = Field(default_factory=UiConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    firewall: FirewallConfig = Field(default_factory=FirewallConfig)
    access: AccessConfig = Field(default_factory=AccessConfig)
    ddns: DdnsConfig = Field(default_factory=DdnsConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)

    @model_validator(mode="before")
    @classmethod
    def reject_lan_sections_on_vps(cls, data: object) -> object:
        """Refuse LAN sections on a VPS before their fields are validated.

        The real error is the section itself, not a missing ``lan_interface`` inside it.
        """
        if not isinstance(data, dict):
            return data
        role = data.get("role")
        if role == Role.VPS:
            present = [section for section in LAN_SECTIONS if section in data]
            if present:
                raise ValueError(
                    "; ".join(f"{section}: not part of role 'vps'" for section in present)
                )
        elif role in (Role.HOME, Role.CLIENT):
            present = [section for section in VPS_SECTIONS if section in data]
            if present:
                raise ValueError(
                    "; ".join(
                        f"{section}: only role 'vps' has a host firewall" for section in present
                    )
                )
        return data

    @model_validator(mode="before")
    @classmethod
    def _vps_panel_default(cls, data: object) -> object:
        """A VPS is a public machine: its panel is off unless config.yaml says otherwise.

        Every other box turns it on by default, because there the panel answers on the LAN only.
        A default that opens a web interface on a rented server is the kind of default nobody
        reads until it is too late.
        """
        if not isinstance(data, dict) or data.get("role") != Role.VPS:
            return data
        if "ui" not in data:
            return {**data, "ui": {"enabled": False}}
        return data

    @model_validator(mode="after")
    def check_role_rules(self) -> Self:
        errors = self._role_errors()
        if errors:
            raise ValueError("; ".join(errors))
        return self

    def _role_errors(self) -> list[str]:
        if self.role is Role.VPS:
            return self._vps_errors()
        errors = self._lan_box_errors()
        if self.access.enabled and self.access.address is None:
            errors.append(
                "access.address: required for the access server of a box at home — the name"
                " its people dial, one that follows the box (ddns)"
            )
        if self.role is Role.HOME and self.upstreams.vps.enabled:
            errors.append(
                "upstreams.vps: role 'home' has no VPS uplink; a box paired with a VPS is role"
                " 'client'"
            )
        if self.role is Role.CLIENT:
            if not self.upstreams.vps.enabled:
                errors.append("upstreams.vps.enabled: must be true for role 'client'")
            if self.provider.enabled:
                errors.append(
                    "provider.enabled: role 'client' runs no node; the node is on the VPS"
                )
        return errors

    def _vps_errors(self) -> list[str]:
        errors: list[str] = []
        if self.wg_server is None:
            errors.append("wg_server: required for role 'vps'")
        if not self.provider.enabled:
            errors.append("provider.enabled: must be true for role 'vps'")
        return errors

    def _lan_box_errors(self) -> list[str]:
        errors: list[str] = []
        if self.network is None:
            errors.append(f"network: required for role '{self.role}'")
        if self.routing is None:
            errors.append(f"routing: required for role '{self.role}'")
        elif self.routing.mode is not RoutingMode.OFF and not self.upstreams.is_key_enabled(
            self.routing.default_upstream
        ):
            errors.append(
                f"routing.default_upstream: '{self.routing.default_upstream}' is not an enabled"
                " uplink"
            )
        if self.routing is not None:
            errors.extend(
                f"routing.fallback: '{key}' is not an enabled uplink"
                for key in self.routing.fallback
                if not self.upstreams.is_key_enabled(key)
            )
        if self.wg_server is not None:
            errors.append("wg_server: only role 'vps' runs the WireGuard server")
        errors.extend(self._device_errors())
        errors.extend(self._domain_errors())
        return errors

    def _domain_errors(self) -> list[str]:
        if self.routing is None:
            return []
        uplinks = {
            DomainVia.VPS: Upstream.VPS,
            DomainVia.DPN: Upstream.DPN,
            DomainVia.TOR: Upstream.TOR,
        }
        channels = self.routing.channels()
        errors = [
            f"routing: {item.subject()} goes via {item.via} but that uplink is not enabled"
            for item in channels
            if item.via in uplinks and not self.upstreams.is_enabled(uplinks[item.via])
        ]
        errors.extend(
            f"routing: {item.subject()} goes via wg {item.uplink} but upstreams.wg has no enabled"
            " exit of that name"
            for item in channels
            if item.via is DomainVia.WG
            and not self.upstreams.is_key_enabled(f"{WG_KEY_PREFIX}{item.uplink}")
        )
        countries = {
            item.country
            for item in channels
            if item.via is DomainVia.DPN and item.country is not None
        }
        if len(countries) > MAX_RULE_COUNTRIES:
            errors.append(
                f"routing: {len(countries)} exit countries, at most {MAX_RULE_COUNTRIES}"
                " (each one is a consumer of its own)"
            )
        return errors

    def _device_errors(self) -> list[str]:
        errors: list[str] = []
        seen_macs: set[str] = set()
        seen_ips: set[IPv4Address] = set()
        for device in self.devices:
            policy_uplink = {
                DevicePolicy.VPS: Upstream.VPS,
                DevicePolicy.DPN: Upstream.DPN,
                DevicePolicy.TOR: Upstream.TOR,
            }.get(device.policy)
            if policy_uplink is not None and not self.upstreams.is_enabled(policy_uplink):
                errors.append(
                    f"devices: {device.name!r} uses policy '{device.policy}' but that uplink"
                    " is not enabled"
                )
            if device.mac is not None:
                if device.mac in seen_macs:
                    errors.append(f"devices: duplicate mac {device.mac}")
                seen_macs.add(device.mac)
            if device.ip is not None:
                if device.ip in seen_ips:
                    errors.append(f"devices: duplicate ip {device.ip}")
                seen_ips.add(device.ip)
        return errors

    def compose_profiles(self) -> list[Profile]:
        """Compose profiles this box needs, in the canonical order of ``Profile``."""
        if self.role is Role.VPS:
            profiles = [Profile.PROVIDER, Profile.WG_SERVER]
            if self.ui.enabled:
                profiles.append(Profile.UI)
            if self.access.enabled:
                profiles.append(Profile.ACCESS)
            return profiles
        wanted = {
            Profile.PROVIDER: self.provider.enabled,
            Profile.CONSUMER: self.upstreams.dpn.enabled,
            Profile.WG_CLIENT: self.role is Role.CLIENT,
            # The generated services carry this profile and the inherited wg-client one, so they
            # start here while the base service, whose file this box has not got, does not.
            Profile.WG_UPLINK: bool(self.upstreams.wg),
            Profile.TOR: self.upstreams.tor.enabled,
            Profile.XRAY: self.upstreams.xray.enabled,
            Profile.ROUTER: True,
            Profile.DHCP: self.network is not None and self.network.mode is NetworkMode.GATEWAY,
            Profile.WIFI: self.network is not None and self.network.wifi is not None,
            Profile.DNS: self.dns.enabled,
            Profile.UI: self.ui.enabled,
            Profile.ACCESS: self.access.enabled,
        }
        return [profile for profile in Profile if wanted.get(profile, False)]

    def access_address(self) -> str | None:
        """What the links of the access server name: ``access.address``, or on a VPS the public
        address its home boxes already dial."""
        if self.access.address is not None:
            return self.access.address
        return self.wg_server.endpoint if self.wg_server is not None else None

    def ui_address(self) -> IPv4Address | None:
        """The one address the panel listens on, or ``None`` when this box runs none.

        A box with a LAN answers there. A VPS answers **inside its tunnel** and nowhere else: the
        panel of a rented server has no business on its public address, and the home boxes that
        may reach it are exactly the ones already inside the tunnel.
        """
        if not self.ui.enabled:
            return None
        if self.network is not None:
            return self.network.lan_address
        return self.wg_server.address if self.wg_server is not None else None

    def env_vars(self) -> dict[str, str]:
        """Values ``vibedpn init`` writes to ``.env`` for ``compose.yaml``; every one is derived.

        ``VIBEDPN_TAG`` is deliberately absent: the image tag is not a property of the box.
        """
        env = {
            "COMPOSE_PROFILES": ",".join(profile.value for profile in self.compose_profiles()),
            "VIBEDPN_API_PORT": str(self.api.port),
        }
        if self.network is not None:
            env["VIBEDPN_LAN_IP"] = str(self.network.lan_address)
        if self.ui.enabled and (address := self.ui_address()) is not None:
            env["VIBEDPN_UI_IP"] = str(address)
            env["VIBEDPN_UI_PORT"] = str(self.ui.port)
            env["VIBEDPN_UI_HOST_NAME"] = self.ui.host_name
            env["VIBEDPN_UI_VARIANT"] = self.ui.variant.value
            env["VIBEDPN_UI_LANGUAGE"] = self.ui.language
            if self.ui.variant is UiVariant.LITE:
                env["VIBEDPN_UI_DB_SHARED_BUFFERS"] = LITE_DB_SHARED_BUFFERS
                env["VIBEDPN_UI_DB_MAX_CONNECTIONS"] = str(LITE_DB_MAX_CONNECTIONS)
        if self.provider.enabled:
            start, end = parse_port_range(self.provider.udp_ports)
            env["VIBEDPN_MYST_UDP_FROM"] = str(start)
            env["VIBEDPN_MYST_UDP_TO"] = str(end)
            env["VIBEDPN_MYST_TRAVERSAL"] = ",".join(t.value for t in self.provider.traversal)
        env.update(self.config_digests())
        return env

    def config_digests(self) -> dict[str, str]:
        """A fingerprint per service of the ``config.yaml`` sections its start-time files come from.

        core renders hostapd.conf, dnsmasq.conf, AdGuardHome.yaml and the tunnel server config only
        when it starts, and applies the firewall and the base of the router there too. Nothing of
        that changes a service in Compose's eyes, so ``up`` would leave them as they are. Each
        service carries its fingerprint in its environment (compose.yaml): a changed section
        recreates exactly core and the services reading its files, and nothing else — a new
        Wi-Fi name does not restart DNS, a new DNS upstream does not drop the Wi-Fi clients.
        Routing, devices, rules and lists are applied live through core and are not part of it.
        Anything else core reads belongs in its fingerprint, even what it only puts into an answer
        (the address in the links): core keeps the config it started with, and a section the CLI
        edits in the file reaches it through a restart alone. tests/test_config_digests.py sorts
        every field of config.yaml into one of these ways and fails on a field it does not know.
        """
        network = self.network.model_dump(mode="json") if self.network is not None else None
        lan = {key: value for key, value in network.items() if key != "wifi"} if network else None
        wifi = (
            {"lan_interface": network["lan_interface"], "wifi": network["wifi"]}
            if network
            else None
        )
        # the files core renders at its start for these services
        rendered: dict[str, object] = {
            DIGEST_HOSTAPD: wifi,
            DIGEST_DNSMASQ: {"lan": lan, "dns": self.dns.enabled},
            DIGEST_ADGUARD: {
                "lan": lan,
                "dns": self.dns.model_dump(mode="json"),
                "ui": {"enabled": self.ui.enabled, "host_name": self.ui.host_name},
            },
            DIGEST_WG_SERVER: (
                self.wg_server.model_dump(mode="json") if self.wg_server is not None else None
            ),
            # What the server itself reads: its port and cover site, and on a LAN box the
            # AdGuard it resolves through. A server that is off reads nothing, and turning it on
            # changes this value, so core renders its files. The address is core's alone (below).
            DIGEST_ACCESS: (
                {
                    "port": self.access.port,
                    "target": self.access.target,
                    "dns": str(self.network.lan_address)
                    if self.network is not None and self.dns.enabled
                    else None,
                }
                if self.access.enabled
                else None
            ),
        }
        core = {
            **rendered,
            "role": self.role.value,
            "network": network,
            "firewall": self.firewall.model_dump(mode="json"),
            "ddns": self.ddns.model_dump(mode="json"),  # the watcher that calls it lives in core
            # the bot lives in core too, and writes its messages in the language of the panel
            "telegram": self.telegram.model_dump(mode="json"),
            "ui_language": self.ui.language,
            # core writes it into every link it hands out, and keeps the config it started with
            "access_address": self.access.address,
            # the kill switch: nothing but an edit of the file changes it
            "failopen": self.routing.failopen if self.routing is not None else None,
            # the uplinks core routes and watches; the CLI turns them on and off in the file
            "uplinks": {
                **{upstream.value: self.upstreams.is_enabled(upstream) for upstream in Upstream},
                "wg": {name: uplink.enabled for name, uplink in self.upstreams.wg.items()},
            },
            # what the firewall of a VPS opens, and the node page core serves
            "provider": {"enabled": self.provider.enabled, "udp_ports": self.provider.udp_ports},
            "ui_port": self.ui.port,
            "api": self.api.model_dump(mode="json"),
        }
        digests = {name: config_digest(payload) for name, payload in rendered.items()}
        # the bridges tor reads at start; the host writes them, core does not read them
        digests[DIGEST_TOR] = config_digest(
            self.upstreams.tor.bridges if self.upstreams.tor.enabled else None
        )
        digests[DIGEST_CORE] = config_digest(core)
        return digests

    def digest_services(self) -> set[str]:
        """The services with a fingerprint that this box actually runs: core always, the others by
        their profile."""
        profiles = set(self.compose_profiles())
        by_profile = {
            "hostapd": Profile.WIFI,
            "dnsmasq": Profile.DHCP,
            "adguard": Profile.DNS,
            "wg-server": Profile.WG_SERVER,
            "access": Profile.ACCESS,
            "tor": Profile.TOR,
        }
        return {"core"} | {
            service for service, profile in by_profile.items() if profile in profiles
        }


class ConfigError(ValueError):
    """``config.yaml`` could not be read: missing file, bad YAML or not a mapping."""


def parse_yaml(text: str) -> object:
    """Parse YAML 1.2 into plain Python objects (the caller narrows the type).

    YAML 1.1 loaders (PyYAML) read ``off``, ``NO`` and ``yes`` as booleans, which breaks
    ``routing.mode: off`` and ``country: NO``. The pure-Python ruamel loader is YAML 1.2, where
    those are strings; ``pure=True`` pins that behaviour regardless of optional C extensions.
    """
    return YAML(typ="safe", pure=True).load(text)


def load_config(path: Path) -> Config:
    """Read and validate ``config.yaml``.

    Raises ``ConfigError`` for file-level problems and ``pydantic.ValidationError`` for schema
    violations; both messages are meant to be shown to the user as they are.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"{path}: not found") from exc
    except OSError as exc:
        raise ConfigError(f"{path}: {exc.strerror or exc}") from exc
    try:
        data = parse_yaml(text)
    except YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: the top level must be a mapping")
    return Config.model_validate(data)
