"""Change routing and device policies in ``config.yaml`` in place; comments and layout stay.

``config.yaml`` is the owner's file: rendering it again from the model would drop their own
comments and ordering. A round-trip load keeps both; the indentation matches the template, so
the diff of ``vibedpn mode full`` is one line. The result is validated with the full model before
it is written, and written atomically — core reads the file at start.
"""

from __future__ import annotations

import io
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from ipaddress import IPv4Address
from pathlib import Path

from pydantic import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import YAMLError

from vibedpn.atomic import write_like
from vibedpn.config import (
    Config,
    DevicePolicy,
    DomainList,
    DomainRule,
    NetworkConfig,
    NetworkRule,
    RoutingMode,
    Weekday,
    normalize_domain,
    normalize_mac,
    parse_yaml,
)

# The layout of templates/config.yaml.j2: lists indented under their key.
MAPPING_INDENT = 2
SEQUENCE_INDENT = 4
SEQUENCE_OFFSET = 2
NO_LINE_WRAP = 4096


class ConfigEditError(ValueError):
    """A user-facing reason why ``config.yaml`` was not changed."""


def round_trip_yaml() -> YAML:
    yaml = YAML(typ="rt", pure=True)
    yaml.preserve_quotes = True
    yaml.indent(mapping=MAPPING_INDENT, sequence=SEQUENCE_INDENT, offset=SEQUENCE_OFFSET)
    yaml.width = NO_LINE_WRAP
    # Round-trip dumps None as an empty value; files written by others (AdGuard spells out
    # `null`) must keep every key we do not own byte for byte.
    yaml.representer.add_representer(
        type(None), lambda dumper, _: dumper.represent_scalar("tag:yaml.org,2002:null", "null")
    )
    return yaml


def _first_problem(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or 'config'}: {error['msg']}"
        for error in exc.errors()
    )


Mutate = Callable[[CommentedMap], None]


def _edit(path: Path, mutate: Mutate) -> tuple[Config, bool]:
    """Load ``path`` round-trip, let ``mutate`` change the document, validate the result with the
    full model and write it atomically; nothing is written when the box would not be valid."""
    yaml = round_trip_yaml()
    try:
        data = yaml.load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigEditError(f"cannot read {path}: {exc.strerror or exc}") from exc
    except YAMLError as exc:
        raise ConfigEditError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(data, CommentedMap):
        raise ConfigEditError(f"{path}: the top level must be a mapping")
    mutate(data)
    buffer = io.StringIO()
    yaml.dump(data, buffer)
    new_text = buffer.getvalue()
    try:
        config = Config.model_validate(parse_yaml(new_text))
    except ValidationError as exc:
        raise ConfigEditError(f"config.yaml not changed: {_first_problem(exc)}") from None
    try:
        changed = write_like(path, new_text)
    except PermissionError:
        raise ConfigEditError(f"cannot write next to {path}; run with sudo") from None
    except OSError as exc:
        raise ConfigEditError(f"cannot write {path}: {exc.strerror or exc}") from exc
    return config, changed


def set_routing(
    path: Path,
    *,
    mode: RoutingMode | None = None,
    upstream: str | None = None,
    fallback: Sequence[str] | None = None,
) -> tuple[Config, bool]:
    """Set ``routing.mode``, ``routing.default_upstream`` and/or ``routing.fallback`` (the whole
    chain; empty removes the key); returns the validated result and whether the file changed.
    Nothing is written when the result would not be a valid box."""

    def mutate(data: CommentedMap) -> None:
        routing = data.get("routing")
        # the loader gives every mapping as CommentedMap: the chain is placed by its order
        if not isinstance(routing, CommentedMap):
            raise ConfigEditError(
                f"{path} has no routing section: a box of this role routes no LAN"
            )
        if mode is not None:
            routing["mode"] = mode.value
        if upstream is not None:
            routing["default_upstream"] = upstream
        if fallback is not None:
            _set_fallback(routing, fallback)

    return _edit(path, mutate)


def _set_fallback(routing: CommentedMap, fallback: Sequence[str]) -> None:
    """The chain on one line, next to failopen, which it extends; no chain removes the key."""
    if not fallback:
        routing.pop("fallback", None)
        return
    chain = CommentedSeq(fallback)
    chain.fa.set_flow_style()
    if "fallback" in routing:
        routing["fallback"] = chain
        return
    keys = list(routing)
    after = keys.index("failopen") + 1 if "failopen" in keys else len(keys)
    routing.insert(after, "fallback", chain)


def set_vps_lan_access(path: Path, allowed: bool) -> tuple[Config, bool]:
    """Open or close the tunnel of the VPS uplink to the LAN (``upstreams.vps.lan_access``)."""

    def mutate(data: CommentedMap) -> None:
        upstreams = data.get("upstreams")
        vps = upstreams.get("vps") if isinstance(upstreams, dict) else None
        if not isinstance(vps, dict):
            raise ConfigEditError(f"{path} has no upstreams.vps section")
        vps["lan_access"] = allowed

    return _edit(path, mutate)


def set_dpn_country(path: Path, country: str | None) -> tuple[Config, bool]:
    """Pin uplink dpn to a country (ISO 3166-1 alpha-2), or let it take any (``None``)."""

    def mutate(data: CommentedMap) -> None:
        upstreams = data.get("upstreams")
        dpn = upstreams.get("dpn") if isinstance(upstreams, dict) else None
        if not isinstance(dpn, dict):
            raise ConfigEditError(f"{path} has no upstreams.dpn section")
        dpn["country"] = country

    return _edit(path, mutate)


def set_tor_uplink(path: Path, enabled: bool) -> tuple[Config, bool]:
    """Turn uplink tor on or off (``upstreams.tor.enabled``); the bridge lines stay as they are."""

    def mutate(data: CommentedMap) -> None:
        upstreams = data.get("upstreams")
        if not isinstance(upstreams, CommentedMap):
            raise ConfigEditError(
                f"{path} has no upstreams section: a box of this role has no uplink"
            )
        tor = upstreams.get("tor")
        if tor is None:
            tor = CommentedMap()
            upstreams["tor"] = tor
        if not isinstance(tor, CommentedMap):
            raise ConfigEditError(f"{path}: upstreams.tor must be a mapping")
        tor["enabled"] = enabled

    return _edit(path, mutate)


def set_xray_uplink(path: Path, enabled: bool) -> tuple[Config, bool]:
    """Turn uplink xray on or off (``upstreams.xray.enabled``); the link itself is a secret and
    never enters config.yaml."""

    def mutate(data: CommentedMap) -> None:
        upstreams = data.get("upstreams")
        if not isinstance(upstreams, CommentedMap):
            raise ConfigEditError(
                f"{path} has no upstreams section: a box of this role has no uplink"
            )
        xray = upstreams.get("xray")
        if xray is None:
            xray = CommentedMap()
            upstreams["xray"] = xray
        if not isinstance(xray, CommentedMap):
            raise ConfigEditError(f"{path}: upstreams.xray must be a mapping")
        xray["enabled"] = enabled

    return _edit(path, mutate)


def set_access(
    path: Path,
    *,
    enabled: bool,
    address: str | None = None,
    port: int | None = None,
    target: str | None = None,
) -> tuple[Config, bool]:
    """Turn the access server on or off and set what its links name; a field left ``None`` stays as
    it is. Its key and its people are secrets and never enter config.yaml."""

    def mutate(data: CommentedMap) -> None:
        section = _section(data, "access", path)
        section["enabled"] = enabled
        for key, value in (("address", address), ("port", port), ("target", target)):
            if value is not None:
                section[key] = value

    return _edit(path, mutate)


def set_ddns(path: Path, enabled: bool) -> tuple[Config, bool]:
    """Turn ddns on or off; the update URL carries a token and lives in ``secrets/``."""

    def mutate(data: CommentedMap) -> None:
        _section(data, "ddns", path)["enabled"] = enabled

    return _edit(path, mutate)


def set_telegram(
    path: Path,
    *,
    enabled: bool | None = None,
    alert_after_seconds: int | None = None,
    timezone: str | None = None,
    report_enabled: bool | None = None,
    report_weekday: Weekday | None = None,
    report_hour: int | None = None,
) -> tuple[Config, bool]:
    """Change the Telegram bot; a field left ``None`` stays as it is. Its token and its chat are
    secrets and never enter config.yaml."""

    def mutate(data: CommentedMap) -> None:
        section = _section(data, "telegram", path)
        fields = (
            ("enabled", enabled),
            ("alert_after_seconds", alert_after_seconds),
            ("timezone", timezone),
        )
        for key, value in fields:
            if value is not None:
                section[key] = value
        weekday = None if report_weekday is None else report_weekday.value
        report = (("enabled", report_enabled), ("weekday", weekday), ("hour", report_hour))
        if any(value is not None for _key, value in report):
            nested = _section(section, "report", path)
            for key, value in report:
                if value is not None:
                    nested[key] = value

    return _edit(path, mutate)


def _section(data: CommentedMap, name: str, path: Path) -> CommentedMap:
    """A section, added when a box set up before it existed has none."""
    section = data.get(name)
    if section is None:
        section = CommentedMap()
        data[name] = section
    if not isinstance(section, CommentedMap):
        raise ConfigEditError(f"{path}: {name} must be a mapping")
    return section


class WgUplinkNotFoundError(ConfigEditError):
    """``config.yaml`` has no named WireGuard exit by this name."""


def _wg_uplinks(data: CommentedMap, path: Path) -> CommentedMap:
    upstreams = data.get("upstreams")
    if not isinstance(upstreams, CommentedMap):
        raise ConfigEditError(f"{path} has no upstreams section: a box of this role has no uplink")
    uplinks = upstreams.get("wg")
    if uplinks is None:
        uplinks = CommentedMap()
        upstreams["wg"] = uplinks
    if not isinstance(uplinks, CommentedMap):
        raise ConfigEditError(f"{path}: upstreams.wg must be a mapping of name to its settings")
    return uplinks


def set_wg_uplink(path: Path, name: str, *, enabled: bool = True) -> tuple[Config, bool]:
    """Add a named WireGuard exit to ``upstreams.wg``, or change whether it is enabled."""

    def mutate(data: CommentedMap) -> None:
        uplinks = _wg_uplinks(data, path)
        entry = uplinks.get(name)
        if isinstance(entry, CommentedMap):
            entry["enabled"] = enabled
            return
        uplinks[name] = CommentedMap({"enabled": enabled})

    return _edit(path, mutate)


def remove_wg_uplink(path: Path, name: str) -> tuple[Config, bool]:
    """Drop a named WireGuard exit; its peer file in ``secrets/`` is left where it is."""

    def mutate(data: CommentedMap) -> None:
        uplinks = _wg_uplinks(data, path)
        if name not in uplinks:
            raise WgUplinkNotFoundError(f"{path} has no WireGuard exit named {name!r}")
        del uplinks[name]

    return _edit(path, mutate)


def set_network(path: Path, network: NetworkConfig) -> tuple[Config, bool]:
    """Replace the keys of the ``network`` section; its comments and the rest of the file stay."""

    def mutate(data: CommentedMap) -> None:
        section = data.get("network")
        if not isinstance(section, CommentedMap):
            raise ConfigEditError(f"{path} has no network section: a box of this role has no LAN")
        values = network.model_dump(mode="json", exclude_none=True)
        for key in [key for key in section if key not in values]:
            del section[key]
        for key, value in values.items():
            section[key] = CommentedMap(value) if isinstance(value, dict) else value

    return _edit(path, mutate)


class DeviceNotFoundError(ConfigEditError):
    """``config.yaml`` has no device with this MAC or address."""


@dataclass(frozen=True)
class DeviceIdent:
    """A device named on the command line or in the API: by MAC, or by IPv4 address."""

    mac: str | None
    ip: IPv4Address | None

    @classmethod
    def parse(cls, text: str) -> DeviceIdent:
        try:
            return cls(normalize_mac(text), None)
        except ValueError:
            pass
        try:
            return cls(None, IPv4Address(text))
        except ValueError:
            raise ConfigEditError(f"{text!r} is neither a MAC nor an IPv4 address") from None

    def matches(self, entry: object) -> bool:
        if not isinstance(entry, dict):
            return False
        if self.mac is not None:
            try:
                return entry.get("mac") is not None and normalize_mac(str(entry["mac"])) == self.mac
            except ValueError:
                return False
        return entry.get("ip") is not None and str(entry["ip"]) == str(self.ip)

    def default_name(self) -> str:
        tail = self.mac.replace(":", "")[-6:] if self.mac else str(self.ip).rsplit(".", 1)[1]
        return f"device-{tail}"


def _device_list(data: CommentedMap) -> CommentedSeq:
    devices = data.get("devices")
    if devices is None:
        devices = CommentedSeq()
        data["devices"] = devices
    if not isinstance(devices, CommentedSeq):
        raise ConfigEditError("config.yaml: devices must be a list")
    # The template writes `devices: []`; entries read better as a block list.
    devices.fa.set_block_style()
    return devices


def set_device(
    path: Path, ident: DeviceIdent, policy: DevicePolicy, name: str | None, default_name: str
) -> tuple[Config, bool]:
    """Give a device its policy: the existing entry changes, or a new one is added (identified by
    the MAC, or by the address when that is all we have). ``name`` renames; ``default_name`` is
    used only for a new entry without one."""

    def mutate(data: CommentedMap) -> None:
        devices = _device_list(data)
        entry = next((item for item in devices if ident.matches(item)), None)
        if entry is None:
            entry = CommentedMap([("name", name or default_name)])
            if ident.mac is not None:
                entry["mac"] = ident.mac
            else:
                entry["ip"] = str(ident.ip)
            entry["policy"] = policy.value
            devices.append(entry)
            return
        entry["policy"] = policy.value
        if name is not None:
            entry["name"] = name

    return _edit(path, mutate)


def unset_device(path: Path, ident: DeviceIdent) -> tuple[Config, bool]:
    """Remove the device's own policy: it follows routing.mode again."""

    def mutate(data: CommentedMap) -> None:
        devices = _device_list(data)
        for index, item in enumerate(devices):
            if ident.matches(item):
                del devices[index]
                return
        raise DeviceNotFoundError(f"config.yaml has no device {ident.mac or ident.ip}")

    return _edit(path, mutate)


class RuleNotFoundError(ConfigEditError):
    """``config.yaml`` has no rule for this domain."""


def _rule_list(data: CommentedMap, path: Path) -> CommentedSeq:
    routing = data.get("routing")
    if not isinstance(routing, CommentedMap):
        raise ConfigEditError(f"{path} has no routing section: a box of this role routes no LAN")
    rules = routing.get("domains")
    if rules is None:
        rules = CommentedSeq()
        routing["domains"] = rules
    if not isinstance(rules, CommentedSeq):
        raise ConfigEditError("config.yaml: routing.domains must be a list")
    rules.fa.set_block_style()  # the template writes `domains: []`
    return rules


def set_domain_rule(path: Path, rule: DomainRule) -> tuple[Config, bool]:
    """Add the rule of a site, or replace the one config.yaml has for that domain."""

    def mutate(data: CommentedMap) -> None:
        rules = _rule_list(data, path)
        entry = CommentedMap([("domain", rule.domain), ("via", rule.via.value)])
        if rule.country is not None:
            entry["country"] = rule.country
        if rule.uplink is not None:
            entry["uplink"] = rule.uplink
        if not rule.learn:
            entry["learn"] = False
        if rule.also:
            entry["also"] = CommentedSeq(rule.also)
        for index, item in enumerate(rules):
            if isinstance(item, dict) and str(item.get("domain", "")).lower() == rule.domain:
                rules[index] = entry
                return
        rules.append(entry)

    return _edit(path, mutate)


def remove_domain_rule(path: Path, domain: str) -> tuple[Config, bool]:
    """Remove the rule of a site: in smart it goes direct again."""
    wanted = normalize_domain(domain)

    def mutate(data: CommentedMap) -> None:
        rules = _rule_list(data, path)
        for index, item in enumerate(rules):
            if isinstance(item, dict) and str(item.get("domain", "")).lower() == wanted:
                del rules[index]
                return
        raise RuleNotFoundError(f"config.yaml has no rule for {wanted}")

    return _edit(path, mutate)


class NetworkRuleNotFoundError(ConfigEditError):
    """``config.yaml`` has no network rule for this network."""


def _network_rules(data: CommentedMap, path: Path) -> CommentedSeq:
    routing = data.get("routing")
    if not isinstance(routing, CommentedMap):
        raise ConfigEditError(f"{path} has no routing section: a box of this role routes no LAN")
    networks = routing.get("networks")
    if networks is None:
        networks = CommentedSeq()
        routing["networks"] = networks
    if not isinstance(networks, CommentedSeq):
        raise ConfigEditError("config.yaml: routing.networks must be a list")
    networks.fa.set_block_style()
    return networks


def set_network_rule(path: Path, rule: NetworkRule) -> tuple[Config, bool]:
    """Add the rule of a network, or replace the one config.yaml has for the same network."""

    def mutate(data: CommentedMap) -> None:
        networks = _network_rules(data, path)
        entry = CommentedMap([("network", str(rule.network)), ("via", rule.via.value)])
        if rule.country is not None:
            entry["country"] = rule.country
        if rule.uplink is not None:
            entry["uplink"] = rule.uplink
        for index, item in enumerate(networks):
            if isinstance(item, dict) and str(item.get("network", "")) == str(rule.network):
                networks[index] = entry
                return
        networks.append(entry)

    return _edit(path, mutate)


def remove_network_rule(path: Path, network: str) -> tuple[Config, bool]:
    """Remove the rule of a network: its addresses go direct in smart again."""

    def mutate(data: CommentedMap) -> None:
        networks = _network_rules(data, path)
        for index, item in enumerate(networks):
            if isinstance(item, dict) and str(item.get("network", "")) == network:
                del networks[index]
                return
        raise NetworkRuleNotFoundError(f"config.yaml has no network rule for {network}")

    return _edit(path, mutate)


class ListNotFoundError(ConfigEditError):
    """``config.yaml`` has no list with this URL."""


def _lists(data: CommentedMap, path: Path) -> CommentedSeq:
    routing = data.get("routing")
    if not isinstance(routing, CommentedMap):
        raise ConfigEditError(f"{path} has no routing section: a box of this role routes no LAN")
    lists = routing.get("lists")
    if lists is None:
        lists = CommentedSeq()
        routing["lists"] = lists
    if not isinstance(lists, CommentedSeq):
        raise ConfigEditError("config.yaml: routing.lists must be a list")
    lists.fa.set_block_style()  # the template writes `lists: []`
    return lists


def set_domain_list(path: Path, item: DomainList) -> tuple[Config, bool]:
    """Add a domain list by URL, or change the channel of the one config.yaml has."""

    def mutate(data: CommentedMap) -> None:
        lists = _lists(data, path)
        entry = CommentedMap([("url", item.url), ("via", item.via.value)])
        if item.country is not None:
            entry["country"] = item.country
        if item.uplink is not None:
            entry["uplink"] = item.uplink
        for index, existing in enumerate(lists):
            if isinstance(existing, dict) and str(existing.get("url", "")) == item.url:
                lists[index] = entry
                return
        lists.append(entry)

    return _edit(path, mutate)


def remove_domain_list(path: Path, url: str) -> tuple[Config, bool]:
    """Remove a domain list: its domains go direct in smart again."""

    def mutate(data: CommentedMap) -> None:
        lists = _lists(data, path)
        for index, existing in enumerate(lists):
            if isinstance(existing, dict) and str(existing.get("url", "")) == url:
                del lists[index]
                return
        raise ListNotFoundError(f"config.yaml has no domain list {url}")

    return _edit(path, mutate)
