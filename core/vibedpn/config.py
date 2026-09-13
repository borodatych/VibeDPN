"""Model of ``config.yaml``: the single source of truth of a VibeDPN box.

The whole v1 schema is declared here so that later stages extend one place. What a ``home``,
``vps`` or ``client`` box must and must not contain is enforced by ``Config`` itself; the
Compose profile preset of a role is derived by :meth:`Config.compose_profiles` and written to
``.env`` by ``vibedpn init``. The human-readable spec of this format, with an example per
role, is ``docs/manuals/configSpec.md``; keep the two in sync.
"""

from __future__ import annotations

import re
from enum import StrEnum
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path
from typing import Annotated, Literal, Self

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
# Postgres of the panel on a lite box (docs/uiVariants.md); a full box keeps the Postgres defaults.
LITE_DB_SHARED_BUFFERS = "32MB"
LITE_DB_MAX_CONNECTIONS = 20
DOH_URL_PATTERN = re.compile(r"^https://[^\s/]+/\S*$")
HOSTNAME_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$"
)
INTERFACE_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,15}$")  # IFNAMSIZ is 16 with the NUL
PORT_MIN = 1
PORT_MAX = 65535
DEFAULT_SSH_PORT = 22
MIN_WG_SUBNET_ADDRESSES = 4  # network, server, at least one peer, broadcast
LAST_PREFIX_WITH_BROADCAST = 30  # /31 and /32 have no reserved network/broadcast addresses
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
    ROUTER = "router"
    DHCP = "dhcp"  # dnsmasq: gateway mode only, never next to the DHCP of an ISP router
    DNS = "dns"
    UI = "ui"


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


class DevicePolicy(StrEnum):
    VPS = "vps"
    DPN = "dpn"
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


def normalize_domain(value: str) -> str:
    """Lower-case a domain suffix, strip surrounding dots; raise ``ValueError`` if invalid."""
    domain = value.lower().strip(".")
    if DOMAIN_PATTERN.fullmatch(domain) is None:
        raise ValueError(f"{value!r} is not a domain name")
    return domain


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


class RoutingConfig(StrictModel):
    """LAN traffic policy: everything direct, everything via an uplink, or by domain list."""

    mode: RoutingMode = RoutingMode.OFF
    default_upstream: Upstream
    failopen: bool = False
    smart_domains: list[str] = Field(default_factory=list)

    @field_validator("smart_domains")
    @classmethod
    def check_domains(cls, domains: list[str]) -> list[str]:
        normalized = [normalize_domain(domain) for domain in domains]
        duplicates = sorted({d for d in normalized if normalized.count(d) > 1})
        if duplicates:
            raise ValueError(f"routing.smart_domains has duplicates: {', '.join(duplicates)}")
        return normalized


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
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"{value!r} is not a country code")
        code = value.strip().upper()
        if COUNTRY_PATTERN.fullmatch(code) is None:
            raise ValueError(f"{value!r} is not an ISO 3166-1 alpha-2 country code")
        return code


class UpstreamsConfig(StrictModel):
    vps: VpsUplink = Field(default_factory=VpsUplink)
    dpn: DpnUplink = Field(default_factory=DpnUplink)

    def is_enabled(self, upstream: Upstream) -> bool:
        return self.vps.enabled if upstream is Upstream.VPS else self.dpn.enabled


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

    @field_validator("host_name")
    @classmethod
    def check_host_name(cls, value: str) -> str:
        return normalize_domain(value)


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


# Sections that describe a LAN-side box and make no sense on a headless VPS.
LAN_SECTIONS = ("network", "routing", "devices", "upstreams", "dns", "ui")
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
        elif self.routing.mode is not RoutingMode.OFF and not self.upstreams.is_enabled(
            self.routing.default_upstream
        ):
            errors.append(
                f"routing.default_upstream: '{self.routing.default_upstream}' is not an enabled"
                " uplink"
            )
        if self.wg_server is not None:
            errors.append("wg_server: only role 'vps' runs the WireGuard server")
        errors.extend(self._device_errors())
        return errors

    def _device_errors(self) -> list[str]:
        errors: list[str] = []
        seen_macs: set[str] = set()
        seen_ips: set[IPv4Address] = set()
        for device in self.devices:
            policy_uplink = {DevicePolicy.VPS: Upstream.VPS, DevicePolicy.DPN: Upstream.DPN}.get(
                device.policy
            )
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
            return [Profile.PROVIDER, Profile.WG_SERVER]
        wanted = {
            Profile.PROVIDER: self.provider.enabled,
            Profile.CONSUMER: self.upstreams.dpn.enabled,
            Profile.WG_CLIENT: self.role is Role.CLIENT,
            Profile.ROUTER: True,
            Profile.DHCP: self.network is not None and self.network.mode is NetworkMode.GATEWAY,
            Profile.DNS: self.dns.enabled,
            Profile.UI: self.ui.enabled,
        }
        return [profile for profile in Profile if wanted.get(profile, False)]

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
            env["VIBEDPN_UI_PORT"] = str(self.ui.port)
            env["VIBEDPN_UI_HOST_NAME"] = self.ui.host_name
            env["VIBEDPN_UI_VARIANT"] = self.ui.variant.value
            if self.ui.variant is UiVariant.LITE:
                env["VIBEDPN_UI_DB_SHARED_BUFFERS"] = LITE_DB_SHARED_BUFFERS
                env["VIBEDPN_UI_DB_MAX_CONNECTIONS"] = str(LITE_DB_MAX_CONNECTIONS)
        if self.provider.enabled:
            start, end = parse_port_range(self.provider.udp_ports)
            env["VIBEDPN_MYST_UDP_FROM"] = str(start)
            env["VIBEDPN_MYST_UDP_TO"] = str(end)
            env["VIBEDPN_MYST_TRAVERSAL"] = ",".join(t.value for t in self.provider.traversal)
        return env


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
